"""
sql_schema_linker.py
--------------------
Reverse-engineers schema links from a ground-truth SQL query + DB schema.

The DIN-SQL paper stores schema links in the format:
    [table.column, table.column, foreign_key_expr, cell_value, ...]

This module extracts that information directly from SQL syntax so we can
pre-populate schema links for all 8659 Spider training examples — giving
the dynamic prompt builder proper <Q, S, A> triples instead of empty [].

Usage:
    from sql_schema_linker import SQLSchemaLinker
    linker = SQLSchemaLinker("data/tables.json")
    links  = linker.extract_links("concert_singer", sql_string)
    # returns: "[singer.Singer_ID, concert.concert_ID = singer_in_concert.Singer_ID, ...]"
"""

import re
import json
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize_sql(sql: str) -> List[str]:
    """Split SQL into tokens, preserving quoted strings as single tokens."""
    # Match quoted strings OR word tokens OR punctuation
    pattern = r"'[^']*'|\"[^\"]*\"|\b\w+\b|[^\w\s]"
    return re.findall(pattern, sql, re.IGNORECASE)


def _strip_quotes(s: str) -> str:
    return s.strip("'\"` ")


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class SQLSchemaLinker:
    """
    Parses tables.json once, then can extract schema links for any SQL
    query against any database in that file.
    """

    def __init__(self, tables_path: str = "data/tables.json"):
        self.db_schemas: Dict[str, dict] = {}
        self._load(tables_path)

    # ------------------------------------------------------------------ load
    def _load(self, path: str):
        with open(path, "r") as f:
            data = json.load(f)

        for db in data:
            db_id = db["db_id"]
            table_names   = [t.lower() for t in db["table_names_original"]]
            col_raw       = db["column_names_original"]   # [[tbl_idx, col], ...]
            col_types     = db["column_types"]
            primary_keys  = db["primary_keys"]            # list of col indices
            foreign_keys  = db["foreign_keys"]            # [[ci1, ci2], ...]

            # Build column index → (table_name, col_name)
            col_index: Dict[int, Tuple[str, str]] = {}
            for ci, (ti, cname) in enumerate(col_raw):
                if ti >= 0:
                    col_index[ci] = (table_names[ti], cname.lower())

            # Build lookup: (table, col) → col_type
            col_type_map: Dict[Tuple[str, str], str] = {}
            for ci, (ti, cname) in enumerate(col_raw):
                if ti >= 0:
                    col_type_map[(table_names[ti], cname.lower())] = col_types[ci]

            # Build set of all column names and table names (lower)
            all_cols   = {c.lower() for _, (_, c) in enumerate(col_raw) if c != "*"}
            all_tables = set(table_names)

            # Build foreign-key pairs as (tbl1.col1, tbl2.col2) strings
            fk_pairs: List[str] = []
            for ci1, ci2 in foreign_keys:
                if ci1 in col_index and ci2 in col_index:
                    t1, c1 = col_index[ci1]
                    t2, c2 = col_index[ci2]
                    fk_pairs.append(f"{t1}.{c1} = {t2}.{c2}")

            self.db_schemas[db_id] = {
                "table_names":  all_tables,
                "all_cols":     all_cols,
                "col_index":    col_index,
                "col_type_map": col_type_map,
                "fk_pairs":     fk_pairs,
            }

    # ------------------------------------------------------ public interface
    def extract_links(self, db_id: str, sql: str) -> str:
        """
        Main method. Returns a schema-links string like the DIN-SQL paper:
            "[singer.Age, concert.Theme = singer_in_concert.concert_ID, 'France']"

        Parameters
        ----------
        db_id : str   e.g. "concert_singer"
        sql   : str   ground-truth SQL from Spider training set

        Returns
        -------
        str  — the Schema_links value, ready to paste into a prompt
        """
        if db_id not in self.db_schemas:
            return "[]"

        schema = self.db_schemas[db_id]
        sql_upper = sql.upper()
        tokens = _tokenize_sql(sql)

        links = []
        seen  = set()   # dedup

        # ── 1. Collect table.column mentions ──────────────────────────────
        # Pattern A: explicit "table.column"
        dotted = re.findall(r"\b(\w+)\.(\w+)\b", sql, re.IGNORECASE)
        for tbl, col in dotted:
            tbl = tbl.lower(); col = col.lower()
            if tbl in schema["table_names"] and col in schema["all_cols"]:
                entry = f"{tbl}.{col}"
                if entry not in seen:
                    links.append(entry)
                    seen.add(entry)

        # Pattern B: bare column names (match against schema)
        # Walk tokens and check if they're column names in this DB
        for tok in tokens:
            tl = tok.lower()
            if tl in schema["all_cols"] and tl not in {"*", "id"}:
                # find which table it belongs to (first match)
                for ci, (tname, cname) in schema["col_index"].items():
                    if cname == tl:
                        entry = f"{tname}.{cname}"
                        if entry not in seen:
                            links.append(entry)
                            seen.add(entry)
                        break

        # ── 2. Add relevant foreign keys ─────────────────────────────────
        # Include an FK pair if both tables appear in the SQL
        tables_in_sql = {
            tok.lower() for tok in tokens
            if tok.lower() in schema["table_names"]
        }
        for fk in schema["fk_pairs"]:
            # fk looks like "singer.Singer_ID = singer_in_concert.Singer_ID"
            parts = fk.replace(" ", "").split("=")
            if len(parts) == 2:
                t1 = parts[0].split(".")[0]
                t2 = parts[1].split(".")[0]
                if t1 in tables_in_sql and t2 in tables_in_sql:
                    if fk not in seen:
                        links.append(fk)
                        seen.add(fk)

        # ── 3. Extract literal cell values from WHERE / HAVING ────────────
        # Grab single-quoted strings and numeric literals after comparison ops
        # Single-quoted strings
        quoted_vals = re.findall(r"'([^']+)'", sql)
        for v in quoted_vals:
            entry = f"'{v}'"
            if entry not in seen:
                links.append(entry)
                seen.add(entry)

        # Numeric literals after = / > / < / >= / <= / !=
        numeric_vals = re.findall(
            r"(?:=|!=|<>|>=|<=|>|<)\s*(\d+(?:\.\d+)?)\b", sql
        )
        for v in numeric_vals:
            if v not in seen:
                links.append(v)
                seen.add(v)

        # ── 4. Handle SELECT * or COUNT(*) ───────────────────────────────
        if re.search(r"\bCOUNT\s*\(\s*\*\s*\)", sql, re.IGNORECASE):
            # find first table used
            for t in tables_in_sql:
                entry = f"{t}.*"
                if entry not in seen:
                    links.append(entry)
                    seen.add(entry)
                break

        if not links:
            return "[]"

        return "[" + ", ".join(links) + "]"


# ---------------------------------------------------------------------------
# Batch enrichment — call this ONCE to add schema_links to mapping.pkl
# ---------------------------------------------------------------------------

def enrich_mapping_with_schema_links(
    mapping_path: str = "vector_store/spider_mapping.pkl",
    tables_path:  str = "data/tables.json",
    output_path:  str = "vector_store/spider_mapping.pkl",
) -> None:
    """
    Loads the FAISS mapping, adds a 'schema_links' field to every entry,
    and saves it back (overwrites by default).

    Run this ONCE after build_vector_store.py:
        python sql_schema_linker.py
    """
    import pickle

    linker = SQLSchemaLinker(tables_path)

    with open(mapping_path, "rb") as f:
        mapping = pickle.load(f)

    enriched = 0
    for item in mapping:
        if "schema_links" not in item:
            item["schema_links"] = linker.extract_links(
                item["db_id"], item["query"]
            )
            enriched += 1

    with open(output_path, "wb") as f:
        pickle.dump(mapping, f)

    print(f"Enriched {enriched}/{len(mapping)} entries with schema_links.")
    print(f"Saved to {output_path}")


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    # --- Unit tests (no Spider data needed) --------------------------------
    print("=" * 60)
    print("sql_schema_linker.py — smoke tests")
    print("=" * 60)

    # Test _tokenize_sql
    sql = "SELECT name FROM singer WHERE Age > 20 AND Country = 'France'"
    toks = _tokenize_sql(sql)
    print(f"\ntokenize_sql: {toks[:10]} ...")

    # Test _strip_quotes
    assert _strip_quotes("'France'") == "France"
    assert _strip_quotes('"hello"') == "hello"
    print("strip_quotes: OK")

    # --- Integration test (needs data/tables.json) -------------------------
    if os.path.exists("data/tables.json"):
        linker = SQLSchemaLinker("data/tables.json")

        test_cases = [
            (
                "concert_singer",
                "SELECT Name FROM singer WHERE Age > 20",
                "expected: singer.Name, singer.Age, 20"
            ),
            (
                "concert_singer",
                "SELECT T1.Name FROM singer AS T1 JOIN singer_in_concert AS T2 ON T1.Singer_ID = T2.Singer_ID",
                "expected: singer.Name + FK"
            ),
            (
                "concert_singer",
                "SELECT Name FROM singer WHERE Country = 'France'",
                "expected: singer.Name, singer.Country, 'France'"
            ),
        ]

        print("\nIntegration tests:")
        for db_id, sql, note in test_cases:
            result = linker.extract_links(db_id, sql)
            print(f"\n  SQL : {sql[:60]}...")
            print(f"  Note: {note}")
            print(f"  Got : {result}")

        # Batch enrichment test
        if os.path.exists("vector_store/spider_mapping.pkl"):
            print("\nRunning batch enrichment...")
            enrich_mapping_with_schema_links()
        else:
            print("\nSkipping batch enrichment (run build_vector_store.py first).")
    else:
        print("\nSkipping integration tests (data/tables.json not found).")
        print("Place Spider dataset in data/ and run again.")
