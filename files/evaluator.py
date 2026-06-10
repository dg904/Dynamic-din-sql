"""
evaluator.py
------------
Evaluation harness for the DIN-SQL extension project.

Implements two official Spider metrics:
  1. Execution Accuracy  (EX)  — do both SQLs return the same result set?
  2. Exact Set Match     (EM)  — do the SQL clauses structurally match?

Also produces a per-difficulty breakdown (easy/medium/hard/extra) and
a per-error-category analysis matching Figure 1 / Figure 4 in the paper.

Usage (standalone):
    python evaluator.py \
        --predicted predicted_sql.txt \
        --gold      data/dev.json \
        --db_dir    data/database \
        --output    results/eval_report.json

Usage (as a library):
    from evaluator import Evaluator
    ev = Evaluator("data/dev.json", "data/database")
    report = ev.evaluate("predicted_sql.txt")
    ev.print_report(report)
"""

import json
import os
import re
import sqlite3
import argparse
import traceback
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# SQL Clause Parsing  (for Exact Set Match)
# ─────────────────────────────────────────────────────────────────────────────

_CLAUSE_KEYWORDS = [
    "SELECT", "FROM", "WHERE", "GROUP BY", "HAVING",
    "ORDER BY", "LIMIT", "INTERSECT", "UNION", "EXCEPT"
]

def _normalize_sql(sql: str) -> str:
    """Light normalization: upper-case keywords, collapse whitespace."""
    sql = re.sub(r"\s+", " ", sql.strip())
    for kw in _CLAUSE_KEYWORDS:
        sql = re.sub(r"\b" + kw + r"\b", kw, sql, flags=re.IGNORECASE)
    return sql


def _parse_clauses(sql: str) -> Dict[str, set]:
    """
    Splits a SQL string into clauses and returns each clause's tokens as a set.
    This is a simplified version of the official Spider EM metric logic.
    """
    sql = _normalize_sql(sql)
    clauses: Dict[str, List[str]] = {kw: [] for kw in _CLAUSE_KEYWORDS}
    current_clause = "SELECT"

    tokens = sql.split()
    i = 0
    while i < len(tokens):
        # Check 2-word keywords first (GROUP BY, ORDER BY)
        two_word = tokens[i] + " " + tokens[i+1] if i + 1 < len(tokens) else ""
        if two_word in _CLAUSE_KEYWORDS:
            current_clause = two_word
            i += 2
            continue
        if tokens[i] in _CLAUSE_KEYWORDS:
            current_clause = tokens[i]
            i += 1
            continue
        clauses[current_clause].append(tokens[i].lower().strip("(),;"))
        i += 1

    return {k: set(v) - {""} for k, v in clauses.items()}


def exact_set_match(pred_sql: str, gold_sql: str) -> bool:
    """
    Returns True if the predicted and gold SQL have matching clause token sets.
    Mirrors the EM metric described in the Spider paper.
    """
    try:
        pred_clauses = _parse_clauses(pred_sql)
        gold_clauses = _parse_clauses(gold_sql)
        for clause in _CLAUSE_KEYWORDS:
            if pred_clauses.get(clause) != gold_clauses.get(clause):
                return False
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Execution Accuracy
# ─────────────────────────────────────────────────────────────────────────────

def _run_query(db_path: str, sql: str, timeout: int = 10) -> Optional[List]:
    """Executes SQL against a SQLite DB file. Returns result rows or None."""
    try:
        conn = sqlite3.connect(db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        conn.close()
        # Normalize: sort rows, lower-case strings
        result = []
        for row in rows:
            normalized = tuple(
                str(v).lower().strip() if v is not None else "null"
                for v in row
            )
            result.append(normalized)
        return sorted(result)
    except Exception:
        return None


def execution_accuracy(pred_sql: str, gold_sql: str, db_path: str) -> bool:
    """
    Returns True if pred and gold SQL return identical result sets.
    """
    pred_result = _run_query(db_path, pred_sql)
    gold_result = _run_query(db_path, gold_sql)

    if pred_result is None or gold_result is None:
        return False
    return pred_result == gold_result


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty Classification  (matches Spider's official bucketing)
# ─────────────────────────────────────────────────────────────────────────────

def _count_components(sql: str) -> Dict[str, int]:
    sql_up = sql.upper()
    return {
        "where":     len(re.findall(r"\bWHERE\b",    sql_up)),
        "group_by":  len(re.findall(r"\bGROUP\s+BY\b", sql_up)),
        "order_by":  len(re.findall(r"\bORDER\s+BY\b", sql_up)),
        "limit":     len(re.findall(r"\bLIMIT\b",    sql_up)),
        "join":      len(re.findall(r"\bJOIN\b",     sql_up)),
        "or":        len(re.findall(r"\bOR\b",       sql_up)),
        "like":      len(re.findall(r"\bLIKE\b",     sql_up)),
        "having":    len(re.findall(r"\bHAVING\b",   sql_up)),
        "nested":    len(re.findall(r"\bSELECT\b",   sql_up)) - 1,  # subqueries
        "except":    len(re.findall(r"\bEXCEPT\b",   sql_up)),
        "union":     len(re.findall(r"\bUNION\b",    sql_up)),
        "intersect": len(re.findall(r"\bINTERSECT\b",sql_up)),
    }


def get_difficulty(sql: str) -> str:
    """
    Replicates Spider's 4-level difficulty bucketing:
      easy / medium / hard / extra
    """
    c = _count_components(sql)

    has_nested      = c["nested"] > 0
    has_set_op      = c["except"] + c["union"] + c["intersect"] > 0
    has_having      = c["having"] > 0
    multi_join      = c["join"] > 1
    many_conditions = c["where"] > 0 and c["or"] > 0

    if has_nested or has_set_op:
        return "extra"
    if has_having or multi_join or many_conditions:
        return "hard"
    if c["join"] == 1 or c["where"] > 0 or c["group_by"] > 0:
        return "medium"
    return "easy"


# ─────────────────────────────────────────────────────────────────────────────
# Error Category Analysis  (matches Figure 1 / Figure 4 in the paper)
# ─────────────────────────────────────────────────────────────────────────────

def categorize_error(pred_sql: str, gold_sql: str) -> str:
    """
    Assigns a failure to one of the paper's 6 error categories.
    Only called when execution_accuracy == False.
    """
    pred_up = pred_sql.upper()
    gold_up = gold_sql.upper()

    pred_joins   = set(re.findall(r"\bJOIN\s+(\w+)\b", pred_up))
    gold_joins   = set(re.findall(r"\bJOIN\s+(\w+)\b", gold_up))
    pred_tables  = set(re.findall(r"\bFROM\s+(\w+)\b", pred_up))
    gold_tables  = set(re.findall(r"\bFROM\s+(\w+)\b", gold_up))

    pred_has_nested = "SELECT" in pred_up[pred_up.find("SELECT")+6:]
    gold_has_nested = "SELECT" in gold_up[gold_up.find("SELECT")+6:]

    # 1. Schema Linking errors (wrong tables or columns in FROM/SELECT)
    if pred_tables != gold_tables:
        return "schema_linking"

    # 2. JOIN errors
    if pred_joins != gold_joins:
        return "join"

    # 3. GROUP BY errors
    pred_gb = re.search(r"GROUP\s+BY\s+([\w\s,]+?)(?:HAVING|ORDER|LIMIT|$)", pred_up)
    gold_gb = re.search(r"GROUP\s+BY\s+([\w\s,]+?)(?:HAVING|ORDER|LIMIT|$)", gold_up)
    if bool(pred_gb) != bool(gold_gb):
        return "group_by"
    if pred_gb and gold_gb and pred_gb.group(1).strip() != gold_gb.group(1).strip():
        return "group_by"

    # 4. Nested / Set operation errors
    pred_has_set = any(k in pred_up for k in ["EXCEPT","UNION","INTERSECT"])
    gold_has_set = any(k in gold_up for k in ["EXCEPT","UNION","INTERSECT"])
    if pred_has_nested != gold_has_nested or pred_has_set != gold_has_set:
        return "nested"

    # 5. Invalid SQL (couldn't execute)
    if _run_query(":memory:", pred_sql) is None:
        return "invalid_sql"

    # 6. Miscellaneous
    return "miscellaneous"


# ─────────────────────────────────────────────────────────────────────────────
# Main Evaluator Class
# ─────────────────────────────────────────────────────────────────────────────

class Evaluator:
    """
    Loads the Spider dev set and a database directory, then evaluates
    a predicted SQL file.

    Parameters
    ----------
    gold_path : str   path to dev.json
    db_dir    : str   path to directory containing per-db SQLite files
                      e.g.  data/database/concert_singer/concert_singer.sqlite
    """

    def __init__(self, gold_path: str = "data/dev.json",
                 db_dir: str = "data/database"):
        with open(gold_path, "r") as f:
            self.gold_data = json.load(f)
        self.db_dir = db_dir

    def _db_path(self, db_id: str) -> str:
        return os.path.join(self.db_dir, db_id, f"{db_id}.sqlite")

    # ---------------------------------------------------------------- evaluate
    def evaluate(
        self,
        predicted_path: str,
        max_samples: Optional[int] = None,
    ) -> Dict:
        """
        Compares predicted SQLs (one per line) against dev.json gold.

        Returns a report dict with overall + per-difficulty metrics.
        """
        with open(predicted_path, "r") as f:
            predicted = [line.strip() for line in f if line.strip()]

        gold = self.gold_data
        if max_samples:
            gold      = gold[:max_samples]
            predicted = predicted[:max_samples]

        if len(predicted) != len(gold):
            print(f"WARNING: {len(predicted)} predictions vs {len(gold)} gold entries.")

        # Counters
        total_ex = total_em = 0
        difficulty_ex  = defaultdict(int)
        difficulty_tot = defaultdict(int)
        error_counts   = defaultdict(int)
        failed_cases   = []

        for i, (item, pred_sql) in enumerate(zip(gold, predicted)):
            gold_sql = item["query"]
            db_id    = item["db_id"]
            question = item["question"]
            diff     = item.get("difficulty") or get_difficulty(gold_sql)
            db_path  = self._db_path(db_id)

            difficulty_tot[diff] += 1

            # ── Execution Accuracy ─────────────────────────────────────
            ex_pass = False
            if os.path.exists(db_path):
                ex_pass = execution_accuracy(pred_sql, gold_sql, db_path)
            else:
                # DB file missing — fall back to EM only
                pass

            # ── Exact Set Match ────────────────────────────────────────
            em_pass = exact_set_match(pred_sql, gold_sql)

            total_ex += int(ex_pass)
            total_em += int(em_pass)
            if ex_pass:
                difficulty_ex[diff] += 1

            # ── Error analysis for failures ────────────────────────────
            if not ex_pass:
                cat = categorize_error(pred_sql, gold_sql)
                error_counts[cat] += 1
                failed_cases.append({
                    "index":    i,
                    "question": question,
                    "db_id":    db_id,
                    "difficulty": diff,
                    "predicted":  pred_sql,
                    "gold":       gold_sql,
                    "error_category": cat,
                })

        n = len(predicted)
        report = {
            "n_samples":  n,
            "execution_accuracy": round(total_ex / n * 100, 2) if n else 0,
            "exact_match":        round(total_em / n * 100, 2) if n else 0,

            # Per-difficulty EX
            "difficulty_breakdown": {
                diff: {
                    "correct": difficulty_ex[diff],
                    "total":   difficulty_tot[diff],
                    "accuracy": round(
                        difficulty_ex[diff] / difficulty_tot[diff] * 100, 2
                    ) if difficulty_tot[diff] else 0,
                }
                for diff in ["easy", "medium", "hard", "extra"]
            },

            # Error categories (matches Figure 4 in paper)
            "error_categories": dict(error_counts),

            # Full list of failures (for deep inspection)
            "failed_cases": failed_cases,
        }
        return report

    # ------------------------------------------------------------------ print
    @staticmethod
    def print_report(report: Dict, show_failures: int = 5):
        """Pretty-prints the evaluation report to stdout."""
        sep = "=" * 60
        print(f"\n{sep}")
        print("  DIN-SQL EXTENDED — EVALUATION REPORT")
        print(sep)
        print(f"  Samples evaluated : {report['n_samples']}")
        print(f"  Execution Accuracy: {report['execution_accuracy']:.1f}%")
        print(f"  Exact Set Match   : {report['exact_match']:.1f}%")

        print(f"\n  Per-Difficulty Breakdown (Execution Accuracy):")
        for diff in ["easy", "medium", "hard", "extra"]:
            b = report["difficulty_breakdown"].get(diff, {})
            acc = b.get("accuracy", 0)
            tot = b.get("total", 0)
            cor = b.get("correct", 0)
            bar = "█" * int(acc / 5)
            print(f"    {diff:8s}  {acc:5.1f}%  {bar:<20s}  ({cor}/{tot})")

        print(f"\n  Error Category Breakdown (failed queries):")
        total_err = sum(report["error_categories"].values())
        for cat, count in sorted(
            report["error_categories"].items(), key=lambda x: -x[1]
        ):
            pct = count / total_err * 100 if total_err else 0
            bar = "█" * int(pct / 5)
            print(f"    {cat:20s}  {pct:5.1f}%  {bar:<20s}  (n={count})")

        if show_failures and report["failed_cases"]:
            print(f"\n  First {show_failures} Failure Cases:")
            for case in report["failed_cases"][:show_failures]:
                print(f"\n    [{case['index']}] {case['db_id']} ({case['difficulty']})")
                print(f"    Q   : {case['question']}")
                print(f"    PRED: {case['predicted']}")
                print(f"    GOLD: {case['gold']}")
                print(f"    ERR : {case['error_category']}")

        print(f"\n{sep}\n")

    # ------------------------------------------------------------------ save
    @staticmethod
    def save_report(report: Dict, output_path: str):
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        # Remove failed_cases from JSON save (can be large)
        save_data = {k: v for k, v in report.items() if k != "failed_cases"}
        save_data["n_failed_cases"] = len(report.get("failed_cases", []))
        with open(output_path, "w") as f:
            json.dump(save_data, f, indent=2)
        print(f"Report saved to {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Comparison helper — baseline vs extension
# ─────────────────────────────────────────────────────────────────────────────

def compare_runs(
    baseline_pred: str,
    extended_pred: str,
    gold_path:     str = "data/dev.json",
    db_dir:        str = "data/database",
):
    """
    Evaluates two prediction files and prints a side-by-side comparison.
    Use this to show the improvement of your extension over original DIN-SQL.

    Example:
        compare_runs("results/baseline.txt", "results/extended.txt")
    """
    ev = Evaluator(gold_path, db_dir)

    print("Evaluating baseline...")
    baseline_report  = ev.evaluate(baseline_pred)

    print("Evaluating extension...")
    extended_report  = ev.evaluate(extended_pred)

    sep = "=" * 60
    print(f"\n{sep}")
    print("  COMPARISON: Baseline DIN-SQL  vs  Extended DIN-SQL")
    print(sep)
    print(f"  {'Metric':<30}  {'Baseline':>10}  {'Extended':>10}  {'Delta':>8}")
    print(f"  {'-'*60}")

    b_ex = baseline_report["execution_accuracy"]
    e_ex = extended_report["execution_accuracy"]
    b_em = baseline_report["exact_match"]
    e_em = extended_report["exact_match"]

    print(f"  {'Execution Accuracy (EX)':<30}  {b_ex:>9.1f}%  {e_ex:>9.1f}%  {e_ex-b_ex:>+7.1f}%")
    print(f"  {'Exact Set Match (EM)':<30}  {b_em:>9.1f}%  {e_em:>9.1f}%  {e_em-b_em:>+7.1f}%")

    print(f"\n  Per-Difficulty EX:")
    for diff in ["easy", "medium", "hard", "extra"]:
        b = baseline_report["difficulty_breakdown"].get(diff, {}).get("accuracy", 0)
        e = extended_report["difficulty_breakdown"].get(diff, {}).get("accuracy", 0)
        print(f"    {diff:8s}  Baseline: {b:5.1f}%   Extended: {e:5.1f}%   Delta: {e-b:+.1f}%")

    print(f"\n{sep}\n")

    return baseline_report, extended_report


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _cli():
    parser = argparse.ArgumentParser(
        description="Evaluate DIN-SQL predictions against Spider dev set."
    )
    parser.add_argument("--predicted",  required=True,
                        help="Path to predicted_sql.txt (one SQL per line)")
    parser.add_argument("--gold",       default="data/dev.json",
                        help="Path to Spider dev.json")
    parser.add_argument("--db_dir",     default="data/database",
                        help="Directory containing SQLite databases")
    parser.add_argument("--output",     default="results/eval_report.json",
                        help="Where to save the JSON report")
    parser.add_argument("--compare",    default=None,
                        help="Optional: second predictions file to compare against")
    parser.add_argument("--max",        type=int, default=None,
                        help="Evaluate only first N samples")
    args = parser.parse_args()

    if args.compare:
        compare_runs(args.predicted, args.compare, args.gold, args.db_dir)
    else:
        ev = Evaluator(args.gold, args.db_dir)
        report = ev.evaluate(args.predicted, max_samples=args.max)
        ev.print_report(report)
        ev.save_report(report, args.output)


if __name__ == "__main__":
    _cli()
