"""
Offline smoke tests for the dynamic demonstration retrieval extension.

These tests avoid OpenAI calls and avoid the full Spider dataset. They check
the pieces that can be verified locally: schema-link extraction, evaluator
metrics, and whether optional retrieval dependencies are installed.
"""

import importlib.util
import json
import os
import sqlite3
import tempfile

from evaluator import Evaluator, exact_set_match, execution_accuracy
from sql_schema_linker import SQLSchemaLinker


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def write_json(path: str, value) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2)


def run() -> dict:
    report = {
        "dependency_check": {
            "numpy": has_module("numpy"),
            "faiss": has_module("faiss"),
            "sentence_transformers": has_module("sentence_transformers"),
            "openai": has_module("openai"),
        },
        "tests": [],
    }

    with tempfile.TemporaryDirectory() as td:
        data_dir = os.path.join(td, "data")
        db_dir = os.path.join(data_dir, "database")
        os.makedirs(os.path.join(db_dir, "school"), exist_ok=True)

        tables_path = os.path.join(data_dir, "tables.json")
        db_path = os.path.join(db_dir, "school", "school.sqlite")
        gold_path = os.path.join(data_dir, "dev.json")
        pred_path = os.path.join(td, "predicted_sql.txt")

        write_json(
            tables_path,
            [
                {
                    "db_id": "school",
                    "table_names_original": ["students"],
                    "column_names_original": [
                        [-1, "*"],
                        [0, "id"],
                        [0, "name"],
                        [0, "age"],
                    ],
                    "column_types": ["text", "number", "text", "number"],
                    "primary_keys": [1],
                    "foreign_keys": [],
                }
            ],
        )

        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE students (id INTEGER, name TEXT, age INTEGER)")
        conn.executemany(
            "INSERT INTO students VALUES (?, ?, ?)",
            [(1, "Asha", 20), (2, "Ravi", 22), (3, "Mina", 22)],
        )
        conn.commit()
        conn.close()

        gold_sql = "SELECT name FROM students WHERE age = 22"
        pred_sql = "SELECT name FROM students WHERE age = 22"
        write_json(
            gold_path,
            [
                {
                    "question": "Which students are 22 years old?",
                    "query": gold_sql,
                    "db_id": "school",
                    "difficulty": "medium",
                }
            ],
        )
        with open(pred_path, "w", encoding="utf-8") as f:
            f.write(pred_sql + "\n")

        linker = SQLSchemaLinker(tables_path)
        links = linker.extract_links("school", gold_sql)
        report["tests"].append(
            {
                "name": "schema_linker_extracts_columns_and_value",
                "passed": "students.name" in links
                and "students.age" in links
                and "22" in links,
                "observed": links,
            }
        )

        report["tests"].append(
            {
                "name": "exact_set_match_identical_sql",
                "passed": exact_set_match(pred_sql, gold_sql),
            }
        )
        report["tests"].append(
            {
                "name": "execution_accuracy_identical_result",
                "passed": execution_accuracy(pred_sql, gold_sql, db_path),
            }
        )

        ev = Evaluator(gold_path, db_dir)
        eval_report = ev.evaluate(pred_path)
        report["tests"].append(
            {
                "name": "evaluator_one_correct_prediction",
                "passed": eval_report["execution_accuracy"] == 100.0
                and eval_report["exact_match"] == 100.0,
                "observed": {
                    "execution_accuracy": eval_report["execution_accuracy"],
                    "exact_match": eval_report["exact_match"],
                },
            }
        )

    report["all_passed"] = all(test["passed"] for test in report["tests"])
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
