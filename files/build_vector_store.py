"""
Build the FAISS vector store used by dynamic_prompt_builder.py.

Expected input:
    data/train_spider.json

Expected output:
    vector_store/spider_faiss.index
    vector_store/spider_mapping.pkl
"""

import argparse
import json
import os
import pickle
from typing import Dict, List

import numpy as np


def classify_complexity(sql: str) -> str:
    """DIN-SQL-style coarse routing labels for prompt selection."""
    sql_up = sql.upper()
    has_nested = sql_up.count("SELECT") > 1
    has_set_op = any(op in sql_up for op in (" INTERSECT ", " UNION ", " EXCEPT "))
    has_join = " JOIN " in f" {sql_up} "

    if has_nested or has_set_op:
        return "NESTED"
    if has_join:
        return "NON-NESTED"
    return "EASY"


def load_training_examples(train_path: str) -> List[Dict[str, str]]:
    with open(train_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    mapping = []
    for item in data:
        query = item["query"]
        mapping.append(
            {
                "question": item["question"],
                "query": query,
                "db_id": item["db_id"],
                "complexity": item.get("complexity") or classify_complexity(query),
            }
        )
    return mapping


def build_vector_store(
    train_path: str = "data/train_spider.json",
    output_dir: str = "vector_store",
    model_name: str = "all-MiniLM-L6-v2",
) -> None:
    try:
        import faiss
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency. Install requirements first: "
            "pip install -r requirements.txt"
        ) from exc

    mapping = load_training_examples(train_path)
    questions = [item["question"] for item in mapping]

    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        questions,
        convert_to_numpy=True,
        show_progress_bar=True,
    ).astype(np.float32)
    faiss.normalize_L2(embeddings)

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)

    os.makedirs(output_dir, exist_ok=True)
    faiss.write_index(index, os.path.join(output_dir, "spider_faiss.index"))
    with open(os.path.join(output_dir, "spider_mapping.pkl"), "wb") as f:
        pickle.dump(mapping, f)

    print(f"Indexed {len(mapping)} Spider training questions.")
    print(f"Saved FAISS index and mapping to {output_dir}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Spider FAISS vector store.")
    parser.add_argument("--train", default="data/train_spider.json")
    parser.add_argument("--output_dir", default="vector_store")
    parser.add_argument("--model", default="all-MiniLM-L6-v2")
    args = parser.parse_args()

    build_vector_store(args.train, args.output_dir, args.model)


if __name__ == "__main__":
    main()
