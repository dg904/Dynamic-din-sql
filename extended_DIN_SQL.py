"""
Extended DIN-SQL benchmark pipeline.

Components:
- Embeddings: SentenceTransformer (local, free)
- Retrieval: FAISS (local, free)
- LLM: NVIDIA NIM — free tier (build.nvidia.com)

Run with environment variable:
    NVIDIA_API_KEY=...

Default validation run:
    python extended_DIN_SQL_new.py

The default sample_size is 50. Reports are written under results/
and are sanitized: API keys and local machine paths are not stored.
"""

import argparse
import json
import os
import pickle
import random
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections import Counter
from typing import Dict, List, Tuple

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

import ssl

# ---------------------------------------------------------------------------
# SSL: disable cert verification globally (handles corporate proxies / DNS
# modifications that break standard cert chains)
# ---------------------------------------------------------------------------
ssl._create_default_https_context = ssl._create_unverified_context
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# ---------------------------------------------------------------------------
# Auto-load .env file if present (so you don't have to export keys every time)
# Supports lines like:  NVIDIA_API_KEY=nvapi-...
# ---------------------------------------------------------------------------
def _load_dotenv(path: str = ".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:   # don't override shell exports
                os.environ[key] = val

_load_dotenv()

from files.evaluator import exact_set_match, execution_accuracy, get_difficulty
from files.sql_schema_linker import SQLSchemaLinker


DEFAULT_SAMPLE_SIZE = 50
DEFAULT_K = 5
RANDOM_SEED = 42
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# NVIDIA NIM — OpenAI-compatible free tier (nvapi- key from build.nvidia.com)
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def classify_complexity(sql: str) -> str:
    sql_up = sql.upper()
    if sql_up.count("SELECT") > 1 or any(op in sql_up for op in [" UNION ", " EXCEPT ", " INTERSECT "]):
        return "NESTED"
    if " JOIN " in f" {sql_up} ":
        return "NON-NESTED"
    return "EASY"


def schema_text_map(tables: list) -> Dict[str, str]:
    out = {}
    for db in tables:
        table_names = db["table_names_original"]
        columns = {table: [] for table in table_names}
        for table_idx, col in db["column_names_original"]:
            if table_idx >= 0 and col != "*":
                columns[table_names[table_idx]].append(col)
        lines = ["Database schema:"]
        for table, cols in columns.items():
            lines.append(f"- {table}({', '.join(cols)})")
        if db.get("foreign_keys"):
            lines.append("Foreign keys:")
            for a, b in db["foreign_keys"]:
                ta, ca = db["column_names_original"][a]
                tb, cb = db["column_names_original"][b]
                if ta >= 0 and tb >= 0:
                    lines.append(f"- {table_names[ta]}.{ca} = {table_names[tb]}.{cb}")
        out[db["db_id"]] = "\n".join(lines)
    return out


def db_path(db_dir: str, db_id: str) -> str:
    return os.path.join(db_dir, db_id, f"{db_id}.sqlite")


def sample_dev(dev: list, db_dir: str, sample_size: int) -> list:
    valid = [item for item in dev if os.path.exists(db_path(db_dir, item["db_id"]))]
    buckets: Dict[str, list] = {"easy": [], "medium": [], "hard": [], "extra": []}
    for item in valid:
        buckets[item.get("difficulty") or get_difficulty(item["query"])].append(item)
    random.seed(RANDOM_SEED)
    selected = []
    per_bucket = max(1, sample_size // 4)
    for diff in ["easy", "medium", "hard", "extra"]:
        random.shuffle(buckets[diff])
        selected.extend(buckets[diff][:per_bucket])
    if len(selected) < sample_size:
        rest = [item for item in valid if item not in selected]
        random.shuffle(rest)
        selected.extend(rest[: sample_size - len(selected)])
    return selected[:sample_size]


def build_or_load_vector_store(
    train_path: str,
    tables_path: str,
    vector_dir: str,
    force_rebuild: bool = False,
) -> Tuple[faiss.Index, list, SentenceTransformer]:
    os.makedirs(vector_dir, exist_ok=True)
    index_path = os.path.join(vector_dir, "spider_faiss.index")
    mapping_path = os.path.join(vector_dir, "spider_mapping.pkl")

    local_only = os.environ.get("HF_LOCAL_FILES_ONLY", "1") != "0"
    model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=local_only)
    if not force_rebuild and os.path.exists(index_path) and os.path.exists(mapping_path):
        index = faiss.read_index(index_path)
        with open(mapping_path, "rb") as f:
            mapping = pickle.load(f)
        return index, mapping, model

    train = load_json(train_path)
    linker = SQLSchemaLinker(tables_path)
    mapping = []
    for item in train:
        mapping.append(
            {
                "question": item["question"],
                "query": item["query"],
                "db_id": item["db_id"],
                "complexity": classify_complexity(item["query"]),
                "schema_links": linker.extract_links(item["db_id"], item["query"]),
            }
        )

    questions = [item["question"] for item in mapping]
    embeddings = model.encode(questions, convert_to_numpy=True, show_progress_bar=True).astype(np.float32)
    faiss.normalize_L2(embeddings)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    faiss.write_index(index, index_path)
    with open(mapping_path, "wb") as f:
        pickle.dump(mapping, f)
    return index, mapping, model


def retrieve_dynamic_examples(question: str, index, mapping: list, model, k: int) -> list:
    emb = model.encode([question], convert_to_numpy=True).astype(np.float32)
    faiss.normalize_L2(emb)
    _, ids = index.search(emb, k)
    return [mapping[i] for i in ids[0]]


def static_examples(mapping: list, k: int) -> list:
    selected = []
    seen = set()
    for label in ["EASY", "NON-NESTED", "NESTED"]:
        for item in mapping:
            if item["complexity"] == label:
                selected.append(item)
                seen.add(id(item))
                break
    for item in mapping:
        if len(selected) >= k:
            break
        if id(item) not in seen:
            selected.append(item)
    return selected[:k]


def build_prompt(item: dict, schema_text: str, examples: list) -> str:
    parts = [
        "Generate exactly one SQLite SQL query for the target question.",
        "Return only SQL. Do not include markdown, comments, or explanation.",
        "",
        "Few-shot examples:",
    ]
    for ex in examples:
        parts.append(f"Q: {ex['question']}")
        parts.append(f"Schema_links: {ex.get('schema_links', '[]')}")
        parts.append(f"SQL: {ex['query']}")
        parts.append("")
    parts.extend(
        [
            "Target database:",
            schema_text,
            "",
            f"Target question: {item['question']}",
            "SQL:",
        ]
    )
    return "\n".join(parts)


def clean_sql(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:sql)?", "", text, flags=re.I).strip()
    text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\b(SELECT|WITH)\b", text, flags=re.I)
    if match:
        text = text[match.start():]
    text = text.splitlines()[0] if text.splitlines() else text
    if ";" in text:
        text = text[: text.index(";") + 1]
    return text.strip().rstrip(";")


def call_nvidia(prompt: str) -> Tuple[str, str]:
    """Call NVIDIA NIM — OpenAI-compatible endpoint (build.nvidia.com)."""
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key:
        print("  [nvidia] No NVIDIA_API_KEY found. Set it in .env or export in shell.", flush=True)
        return "", "nvidia_no_key"
    try:
        import requests as _req
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except ImportError:
        print("  [nvidia] Install requests:  pip install requests", flush=True)
        return "", "nvidia_missing_requests"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    payload = {
        "model": NVIDIA_MODEL,
        "messages": [
            {"role": "system", "content": "You are a precise SQLite text-to-SQL generator."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 256,
    }
    for attempt in range(3):
        try:
            resp = _req.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
                verify=False,
            )
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"]
                return clean_sql(text), "nvidia_ok"
            detail = resp.text[:300].replace("\n", " ")
            print(f"  [nvidia] HTTP {resp.status_code}: {detail}", flush=True)
            if resp.status_code in (401, 403):
                return "", f"nvidia_http_{resp.status_code}"
            if resp.status_code == 429:
                time.sleep(5)
        except Exception as exc:
            wait = 2 ** attempt
            print(f"  [nvidia/retry {attempt+1}] {type(exc).__name__}: {exc} — waiting {wait}s", flush=True)
            time.sleep(wait)
    return "", "nvidia_failed"


def call_llm(prompt: str) -> Tuple[str, str]:
    """Call NVIDIA NIM exclusively."""
    return call_nvidia(prompt)


def evaluate(item: dict, pred: str, db_dir: str) -> dict:
    gold = item["query"]
    has_prediction = bool(pred.strip())
    return {
        "db_id": item["db_id"],
        "question": item["question"],
        "difficulty": item.get("difficulty") or get_difficulty(gold),
        "gold": gold,
        "predicted": pred,
        "execution_correct": execution_accuracy(pred, gold, db_path(db_dir, item["db_id"])) if has_prediction else False,
        "exact_match": exact_set_match(pred, gold) if has_prediction else False,
    }


def metric_block(rows: list) -> dict:
    if not rows:
        return {"n": 0, "execution_accuracy": 0, "exact_match": 0, "by_difficulty": {}}
    out = {
        "n": len(rows),
        "execution_accuracy": round(sum(r["execution_correct"] for r in rows) / len(rows) * 100, 2),
        "exact_match": round(sum(r["exact_match"] for r in rows) / len(rows) * 100, 2),
        "by_difficulty": {},
    }
    for diff in ["easy", "medium", "hard", "extra"]:
        subset = [r for r in rows if r["difficulty"] == diff]
        if subset:
            out["by_difficulty"][diff] = {
                "n": len(subset),
                "execution_accuracy": round(sum(r["execution_correct"] for r in subset) / len(subset) * 100, 2),
                "exact_match": round(sum(r["exact_match"] for r in subset) / len(subset) * 100, 2),
            }
    return out


def summarize(rows: list, latencies: list, statuses: Counter) -> dict:
    generated = [r for r in rows if r["predicted"].strip()]
    summary = metric_block(rows)
    summary.update(
        {
            "completed_generations": len(generated),
            "generation_success_rate": round(len(generated) / len(rows) * 100, 2) if rows else 0,
            "generated_only": metric_block(generated),
            "avg_latency_sec": round(sum(latencies) / len(latencies), 3) if latencies else 0,
            "api_statuses": dict(statuses),
        }
    )
    return summary


def write_predictions(path: str, rows: list):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(row["predicted"].replace("\n", " ") + "\n")


def write_report(path: str, report: dict):
    static = report["runs"]["static"]["summary"]
    dynamic = report["runs"]["dynamic"]["summary"]
    mode = report.get("mode", "benchmark")
    lines = [
        "# Extended DIN-SQL Results",
        "",
        "Sanitized report: no API keys or local machine paths are included.",
        "",
        f"Dataset: Spider dev sample ({report['sample_size']} questions)",
        f"Embedding retrieval: {EMBEDDING_MODEL} + FAISS",
        f"LLM: NVIDIA NIM {NVIDIA_MODEL}",
        f"Mode: {mode}",
        "",
    ]
    if report.get("status"):
        lines.extend([report["status"], ""])
    lines.extend(
        [
        "## Overall Results",
        "",
        "| Method | Samples | Completed | EX | EM | EX Completed Only | EM Completed Only | Avg Latency Sec |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        f"| Static fixed examples | {static['n']} | {static['completed_generations']} | {static['execution_accuracy']} | {static['exact_match']} | {static['generated_only']['execution_accuracy']} | {static['generated_only']['exact_match']} | {static['avg_latency_sec']} |",
        f"| Dynamic FAISS retrieval | {dynamic['n']} | {dynamic['completed_generations']} | {dynamic['execution_accuracy']} | {dynamic['exact_match']} | {dynamic['generated_only']['execution_accuracy']} | {dynamic['generated_only']['exact_match']} | {dynamic['avg_latency_sec']} |",
        "",
        "## Dynamic Retrieval By Difficulty",
        "",
        "| Difficulty | Samples | EX | EM |",
        "|---|---:|---:|---:|",
        ]
    )
    for diff, row in dynamic["by_difficulty"].items():
        lines.append(f"| {diff} | {row['n']} | {row['execution_accuracy']} | {row['exact_match']} |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- All API calls go exclusively to NVIDIA NIM.",
            "- Use a larger sample or the full dev set only after the 50-question run is stable.",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run(args):
    train_path = os.path.join(args.spider_dir, "train_spider.json")
    dev_path = os.path.join(args.spider_dir, "dev.json")
    tables_path = os.path.join(args.spider_dir, "tables.json")
    db_dir = os.path.join(args.spider_dir, "database")
    output_dir = "results"
    os.makedirs(output_dir, exist_ok=True)

    tables = load_json(tables_path)
    schemas = schema_text_map(tables)
    index, mapping, embedder = build_or_load_vector_store(train_path, tables_path, args.vector_dir, args.rebuild_index)
    dev = load_json(dev_path)
    sample = sample_dev(dev, db_dir, args.sample_size)
    fixed_examples = static_examples(mapping, args.k)

    if args.prepare_only:
        report = {
            "dataset": "Spider dev sample",
            "sample_size": len(sample),
            "k_examples": args.k,
            "embedding_model": EMBEDDING_MODEL,
            "nvidia_model": NVIDIA_MODEL,
            "mode": "prepare_only",
            "status": "Vector store and sample selection are ready. No API calls were made.",
        }
        with open(os.path.join(output_dir, "extended_din_sql_prepare_status.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        write_report(os.path.join(output_dir, "extended_din_sql_prepare_status.md"), {
            **report,
            "runs": {
                "static": {"summary": summarize([], [], Counter())},
                "dynamic": {"summary": summarize([], [], Counter())},
            },
        })
        print(json.dumps(report, indent=2))
        return

    runs = {}
    for method in ["static", "dynamic"]:
        rows, latencies, statuses = [], [], Counter()
        for item in sample:
            examples = fixed_examples if method == "static" else retrieve_dynamic_examples(
                item["question"], index, mapping, embedder, args.k
            )
            prompt = build_prompt(item, schemas[item["db_id"]], examples)
            start = time.perf_counter()
            pred, status = call_llm(prompt)
            latencies.append(round(time.perf_counter() - start, 3))
            statuses[status] += 1
            rows.append(evaluate(item, pred, db_dir))
            print(f"  [{method}] {item['db_id']} | {status} | pred: {repr(pred[:60]) if pred else 'EMPTY'}", flush=True)
            time.sleep(0.5)  # avoid bursting rate limits
        runs[method] = {"summary": summarize(rows, latencies, statuses), "cases": rows}
        write_predictions(os.path.join(output_dir, f"extended_{method}_predictions.sql"), rows)

    report = {
        "dataset": "Spider dev sample",
        "sample_size": len(sample),
        "k_examples": args.k,
        "embedding_model": EMBEDDING_MODEL,
        "nvidia_model": NVIDIA_MODEL,
        "runs": runs,
    }
    with open(os.path.join(output_dir, "extended_din_sql_results.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    write_report(os.path.join(output_dir, "extended_din_sql_results.md"), report)
    print(json.dumps({k: v["summary"] for k, v in runs.items()}, indent=2))


def test_api_connectivity():
    """Smoke-test NVIDIA NIM."""
    tiny = "Return only SQL, no explanation: SELECT 1"

    print("=" * 65)
    print("API connectivity test — key loaded from .env + shell environment")
    print("=" * 65)

    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    key_display = f"SET ({key[:8]}...)" if key else "NOT SET (skipped)"
    print(f"\n[NVIDIA]  NVIDIA_API_KEY: {key_display}")
    if key:
        sql, status = call_nvidia(tiny)
        if sql and "ok" in status:
            print(f"  OK  response: {repr(sql)}")
        else:
            print(f"  FAIL  status: {status}")

    print()
    print("=" * 65)
    print("Hints:")
    print("  no_key       -> add NVIDIA_API_KEY to your .env file")
    print("  HTTP 401/403 -> key is wrong or IP is blocked")
    print("  HTTP 429     -> rate limit hit; wait a minute and retry")
    print("  getaddrinfo  -> DNS/network issue")
    print()
    print(".env file template:")
    print("  NVIDIA_API_KEY=nvapi-xxxx    # build.nvidia.com — free tier")
    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="Run Extended DIN-SQL with FAISS retrieval and NVIDIA NIM.")
    parser.add_argument("--spider_dir", default="spider")
    parser.add_argument("--sample_size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--vector_dir", default="vector_store")
    parser.add_argument("--rebuild_index", action="store_true")
    parser.add_argument(
        "--prepare_only",
        action="store_true",
        help="Build/load vector store and write readiness status without making any LLM API calls.",
    )
    parser.add_argument(
        "--test_api",
        action="store_true",
        help="Send a tiny test prompt to NVIDIA NIM to verify key and connectivity, then exit.",
    )
    args = parser.parse_args()
    if args.test_api:
        test_api_connectivity()
        return
    run(args)


if __name__ == "__main__":
    main()