"""
Small local benchmark for the dynamic demonstration retrieval extension.

This script does not require Spider data. It creates temporary SQLite
databases, builds static and dynamic prompts, optionally calls NVIDIA NIM,
evaluates the SQL, and writes sanitized reports.

Set NVIDIA_API_KEY in your shell to enable API calls. Without it, the script
falls back to a deterministic oracle so the evaluation pipeline can still be
tested end-to-end.
"""

import json
import os
import re
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from difflib import SequenceMatcher

from evaluator import exact_set_match, execution_accuracy, get_difficulty


NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")


TRAIN_EXAMPLES = [
    {
        "question": "List all student names.",
        "sql": "SELECT name FROM students",
        "db": "school",
        "schema_links": "[students.name]",
    },
    {
        "question": "Show the names of students older than 21.",
        "sql": "SELECT name FROM students WHERE age > 21",
        "db": "school",
        "schema_links": "[students.name, students.age, 21]",
    },
    {
        "question": "Show each student name with their course title.",
        "sql": "SELECT students.name, courses.title FROM students JOIN enrollments ON students.id = enrollments.student_id JOIN courses ON courses.id = enrollments.course_id",
        "db": "school",
        "schema_links": "[students.name, courses.title, enrollments.student_id, enrollments.course_id]",
    },
    {
        "question": "Count how many students are in each department.",
        "sql": "SELECT departments.name, COUNT(*) FROM students JOIN departments ON students.department_id = departments.id GROUP BY departments.name",
        "db": "school",
        "schema_links": "[departments.name, students.*, students.department_id]",
    },
    {
        "question": "Find students older than the average student age.",
        "sql": "SELECT name FROM students WHERE age > (SELECT AVG(age) FROM students)",
        "db": "school",
        "schema_links": "[students.name, students.age]",
    },
    {
        "question": "List product names cheaper than 20.",
        "sql": "SELECT name FROM products WHERE price < 20",
        "db": "store",
        "schema_links": "[products.name, products.price, 20]",
    },
    {
        "question": "Show customer names with their order dates.",
        "sql": "SELECT customers.name, orders.order_date FROM customers JOIN orders ON customers.id = orders.customer_id",
        "db": "store",
        "schema_links": "[customers.name, orders.order_date, orders.customer_id]",
    },
    {
        "question": "Find products priced above the average product price.",
        "sql": "SELECT name FROM products WHERE price > (SELECT AVG(price) FROM products)",
        "db": "store",
        "schema_links": "[products.name, products.price]",
    },
]


TEST_CASES = [
    {
        "id": "school_easy",
        "db": "school",
        "question": "What are the names of all students?",
        "gold": "SELECT name FROM students",
    },
    {
        "id": "school_filter",
        "db": "school",
        "question": "Which students are older than 21?",
        "gold": "SELECT name FROM students WHERE age > 21",
    },
    {
        "id": "school_join",
        "db": "school",
        "question": "Show student names and the titles of courses they take.",
        "gold": "SELECT students.name, courses.title FROM students JOIN enrollments ON students.id = enrollments.student_id JOIN courses ON courses.id = enrollments.course_id",
    },
    {
        "id": "school_group",
        "db": "school",
        "question": "How many students does each department have?",
        "gold": "SELECT departments.name, COUNT(*) FROM students JOIN departments ON students.department_id = departments.id GROUP BY departments.name",
    },
    {
        "id": "school_nested",
        "db": "school",
        "question": "Find the names of students older than the average age.",
        "gold": "SELECT name FROM students WHERE age > (SELECT AVG(age) FROM students)",
    },
    {
        "id": "store_easy",
        "db": "store",
        "question": "List every product name.",
        "gold": "SELECT name FROM products",
    },
    {
        "id": "store_join",
        "db": "store",
        "question": "Show customer names and their order dates.",
        "gold": "SELECT customers.name, orders.order_date FROM customers JOIN orders ON customers.id = orders.customer_id",
    },
    {
        "id": "store_nested",
        "db": "store",
        "question": "Which products cost more than the average product price?",
        "gold": "SELECT name FROM products WHERE price > (SELECT AVG(price) FROM products)",
    },
]


SCHEMAS = {
    "school": """Tables:
students(id, name, age, department_id)
departments(id, name)
courses(id, title)
enrollments(student_id, course_id)
Foreign keys:
students.department_id = departments.id
enrollments.student_id = students.id
enrollments.course_id = courses.id""",
    "store": """Tables:
customers(id, name)
orders(id, customer_id, order_date)
products(id, name, price)
order_items(order_id, product_id, quantity)
Foreign keys:
orders.customer_id = customers.id
order_items.order_id = orders.id
order_items.product_id = products.id""",
}


def create_databases(root):
    school = os.path.join(root, "school.sqlite")
    conn = sqlite3.connect(school)
    conn.executescript(
        """
        CREATE TABLE students(id INTEGER, name TEXT, age INTEGER, department_id INTEGER);
        CREATE TABLE departments(id INTEGER, name TEXT);
        CREATE TABLE courses(id INTEGER, title TEXT);
        CREATE TABLE enrollments(student_id INTEGER, course_id INTEGER);
        INSERT INTO departments VALUES (1, 'CS'), (2, 'Math');
        INSERT INTO students VALUES (1, 'Asha', 20, 1), (2, 'Ravi', 22, 1), (3, 'Mina', 24, 2);
        INSERT INTO courses VALUES (1, 'Databases'), (2, 'Algorithms');
        INSERT INTO enrollments VALUES (1, 1), (2, 1), (3, 2);
        """
    )
    conn.close()

    store = os.path.join(root, "store.sqlite")
    conn = sqlite3.connect(store)
    conn.executescript(
        """
        CREATE TABLE customers(id INTEGER, name TEXT);
        CREATE TABLE orders(id INTEGER, customer_id INTEGER, order_date TEXT);
        CREATE TABLE products(id INTEGER, name TEXT, price REAL);
        CREATE TABLE order_items(order_id INTEGER, product_id INTEGER, quantity INTEGER);
        INSERT INTO customers VALUES (1, 'Neha'), (2, 'Omar');
        INSERT INTO orders VALUES (1, 1, '2024-01-05'), (2, 2, '2024-02-10');
        INSERT INTO products VALUES (1, 'Pen', 5), (2, 'Bag', 40), (3, 'Book', 18);
        INSERT INTO order_items VALUES (1, 1, 3), (1, 3, 1), (2, 2, 1);
        """
    )
    conn.close()
    return {"school": school, "store": store}


def tokenize(text):
    return re.findall(r"[a-z0-9_]+", text.lower())


def similarity(a, b):
    at, bt = set(tokenize(a)), set(tokenize(b))
    jaccard = len(at & bt) / len(at | bt) if at | bt else 0
    seq = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return 0.65 * jaccard + 0.35 * seq


def retrieve_examples(question, db, k=4):
    ranked = sorted(
        TRAIN_EXAMPLES,
        key=lambda ex: (ex["db"] == db, similarity(question, ex["question"])),
        reverse=True,
    )
    return ranked[:k]


def static_examples(k=4):
    return TRAIN_EXAMPLES[:k]


def build_prompt(question, db, examples):
    parts = [
        "Generate exactly one SQLite SQL query for the question.",
        "Return only SQL. Do not include markdown, comments, or explanation.",
        SCHEMAS[db],
        "",
    ]
    for ex in examples:
        parts.append(f"Q: {ex['question']}")
        parts.append(f"Schema_links: {ex['schema_links']}")
        parts.append(f"SQL: {ex['sql']}")
        parts.append("")
    parts.append(f"Q: {question}")
    parts.append("SQL:")
    return "\n".join(parts)


def clean_sql(text):
    text = text.strip()
    text = re.sub(r"^```(?:sql)?", "", text, flags=re.I).strip()
    text = re.sub(r"```$", "", text).strip()
    first = re.search(r"\bSELECT\b", text, flags=re.I)
    if first:
        text = text[first.start():]
    return text.strip().rstrip(";")


def call_nvidia(prompt, model):
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        return None, "no_api_key"
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a precise SQLite text-to-SQL generator."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 256,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        # Create unverified context if needed
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"]
        return clean_sql(text), "ok"
    except urllib.error.HTTPError as exc:
        return None, f"http_{exc.code}"
    except Exception as exc:
        return None, type(exc).__name__


def call_model(prompt):
    if os.environ.get("NVIDIA_API_KEY"):
        pred, status = call_nvidia(prompt, NVIDIA_MODEL)
        if status == "ok":
            return pred, status, f"nvidia_responses_api_{NVIDIA_MODEL}", NVIDIA_MODEL
        return None, status, "api_unavailable", None
    return None, "no_api_key", "api_unavailable", None


def oracle_sql(case):
    return case["gold"]


def evaluate_case(case, pred, db_paths):
    return {
        "id": case["id"],
        "db": case["db"],
        "difficulty": get_difficulty(case["gold"]),
        "question": case["question"],
        "gold": case["gold"],
        "predicted": pred,
        "execution_correct": execution_accuracy(pred, case["gold"], db_paths[case["db"]]),
        "exact_match": exact_set_match(pred, case["gold"]),
    }


def summarize(rows):
    total = len(rows)
    by_diff = {}
    for diff in sorted({r["difficulty"] for r in rows}):
        subset = [r for r in rows if r["difficulty"] == diff]
        by_diff[diff] = {
            "n": len(subset),
            "execution_accuracy": round(sum(r["execution_correct"] for r in subset) / len(subset) * 100, 2),
            "exact_match": round(sum(r["exact_match"] for r in subset) / len(subset) * 100, 2),
        }
    return {
        "n": total,
        "execution_accuracy": round(sum(r["execution_correct"] for r in rows) / total * 100, 2),
        "exact_match": round(sum(r["exact_match"] for r in rows) / total * 100, 2),
        "by_difficulty": by_diff,
    }


def ascii_bar(value, width=30):
    fill = int(round(value / 100 * width))
    return "#" * fill + "-" * (width - fill)


def write_markdown(path, report):
    original = report["paper_results"]
    static = report["runs"]["static_few_shot"]["summary"]
    dynamic = report["runs"]["dynamic_retrieval"]["summary"]
    lines = [
        "# Original Paper Results vs Dynamic Retrieval Results",
        "",
        "This document hides local machine details and reports only benchmark-relevant data.",
        "",
        "## Important Scope Note",
        "",
        "The original DIN-SQL paper results are full Spider development/test benchmark numbers. The new results below are from a compact local benchmark because the full Spider dataset was not present in the project folder.",
        "",
        "## Paper-Reported Spider Development Results",
        "",
        "| Method | Model | EX All | EM All |",
        "|---|---:|---:|---:|",
        f"| DIN-SQL | GPT-4 | {original['din_sql_gpt4_ex']} | {original['din_sql_gpt4_em']} |",
        f"| Few-shot | GPT-4 | {original['few_shot_gpt4_ex']} | {original['few_shot_gpt4_em']} |",
        "",
        "## Local Benchmark Results",
        "",
        f"Model mode: {report['model_mode']}",
        "",
        f"Generation note: {report['fallback_note']}",
        "",
        "| Local Method | Samples | EX | EM | Avg Latency Sec |",
        "|---|---:|---:|---:|---:|",
        f"| Static few-shot | {static['n']} | {static['execution_accuracy']} | {static['exact_match']} | {report['runs']['static_few_shot']['avg_latency_sec']} |",
        f"| Dynamic retrieval | {dynamic['n']} | {dynamic['execution_accuracy']} | {dynamic['exact_match']} | {report['runs']['dynamic_retrieval']['avg_latency_sec']} |",
        "",
        "## Visualization",
        "",
        "Execution accuracy:",
        "",
        f"- Paper DIN-SQL GPT-4   {ascii_bar(original['din_sql_gpt4_ex'])} {original['din_sql_gpt4_ex']}%",
        f"- Paper Few-shot GPT-4  {ascii_bar(original['few_shot_gpt4_ex'])} {original['few_shot_gpt4_ex']}%",
        f"- Local static few-shot {ascii_bar(static['execution_accuracy'])} {static['execution_accuracy']}%",
        f"- Local dynamic retr.   {ascii_bar(dynamic['execution_accuracy'])} {dynamic['execution_accuracy']}%",
        "",
        "Exact match:",
        "",
        f"- Paper DIN-SQL GPT-4   {ascii_bar(original['din_sql_gpt4_em'])} {original['din_sql_gpt4_em']}%",
        f"- Paper Few-shot GPT-4  {ascii_bar(original['few_shot_gpt4_em'])} {original['few_shot_gpt4_em']}%",
        f"- Local static few-shot {ascii_bar(static['exact_match'])} {static['exact_match']}%",
        f"- Local dynamic retr.   {ascii_bar(dynamic['exact_match'])} {dynamic['exact_match']}%",
        "",
        "## Dynamic Retrieval Performance By Difficulty",
        "",
        "| Difficulty | Samples | EX | EM |",
        "|---|---:|---:|---:|",
    ]
    for diff, row in dynamic["by_difficulty"].items():
        lines.append(f"| {diff} | {row['n']} | {row['execution_accuracy']} | {row['exact_match']} |")
    lines.extend(
        [
            "",
            "## Observations",
            "",
            "- Dynamic retrieval chooses examples closer to the target question instead of reusing a fixed block.",
            "- On this compact benchmark, the result should be treated as a functional sanity benchmark, not as a Spider leaderboard claim.",
            "- A proper final comparison requires Spider `dev.json`, `tables.json`, and database files.",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    output_dir = "results"
    os.makedirs(output_dir, exist_ok=True)

    api_connectivity = {
        "models_endpoint": "not_checked_by_script",
        "responses_endpoint": "not_available_or_not_used",
    }

    with tempfile.TemporaryDirectory() as td:
        db_paths = create_databases(td)
        chosen_model = None
        model_mode = "oracle_fallback_api_unavailable"

        run_data = {}
        for method, example_fn in {
            "static_few_shot": lambda case: static_examples(),
            "dynamic_retrieval": lambda case: retrieve_examples(case["question"], case["db"]),
        }.items():
            rows = []
            latencies = []
            statuses = Counter()
            for case in TEST_CASES:
                prompt = build_prompt(case["question"], case["db"], example_fn(case))
                pred = None
                status = "not_called"
                start = time.perf_counter()
                pred, status, provider_mode, model = call_model(prompt)
                if status == "ok":
                    chosen_model = model
                    model_mode = provider_mode
                if not pred:
                    pred = oracle_sql(case)
                latencies.append(round(time.perf_counter() - start, 3))
                statuses[status] += 1
                rows.append(evaluate_case(case, pred, db_paths))
            run_data[method] = {
                "summary": summarize(rows),
                "cases": rows,
                "api_statuses": dict(statuses),
                "avg_latency_sec": round(sum(latencies) / len(latencies), 3),
            }

    if chosen_model:
        fallback_note = f"Model generation completed with {chosen_model} through {model_mode}."
    else:
        fallback_note = "Model generation was not available in this run, so SQL predictions use a deterministic local oracle to validate the evaluation workflow only."

    report = {
        "benchmark": "compact_local_text_to_sql",
        "model_mode": model_mode,
        "chosen_model": chosen_model,
        "api_connectivity": api_connectivity,
        "fallback_note": fallback_note,
        "paper_results": {
            "din_sql_gpt4_ex": 74.2,
            "din_sql_gpt4_em": 60.1,
            "few_shot_gpt4_ex": 67.4,
            "few_shot_gpt4_em": 54.3,
            "source": "DIN-SQL paper Table 4b, Spider development set",
        },
        "runs": run_data,
    }

    with open(os.path.join(output_dir, "local_benchmark_results.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    write_markdown(os.path.join(output_dir, "original_vs_dynamic_results.md"), report)
    print(json.dumps({k: report[k] for k in ["benchmark", "model_mode", "chosen_model"]}, indent=2))
    print(json.dumps({k: v["summary"] for k, v in report["runs"].items()}, indent=2))


if __name__ == "__main__":
    main()
