"""
dynamic_prompt_builder.py  (updated — uses enriched schema links)
------------------------------------------------------------------
After running:
    python build_vector_store.py
    python sql_schema_linker.py      ← adds schema_links to mapping

every entry in spider_mapping.pkl has the shape:
    {
      'question':    str,
      'query':       str,
      'db_id':       str,
      'complexity':  'EASY' | 'NON-NESTED' | 'NESTED',
      'schema_links': str   ← e.g. "[singer.Age, singer.Country, 'France']"
    }

This file uses those links to build proper <Q, S, A> triples for every
module, matching the DIN-SQL paper's prompt format.
"""

import pickle
import numpy as np


class DynamicPromptBuilder:

    def __init__(self,
                 index_path: str = "vector_store/spider_faiss.index",
                 map_path:   str = "vector_store/spider_mapping.pkl"):
        try:
            import faiss
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "Missing retrieval dependency. Install requirements first: "
                "pip install -r requirements.txt"
            ) from e

        self.faiss = faiss
        try:
            self.index = faiss.read_index(index_path)
            with open(map_path, "rb") as f:
                self.mapping = pickle.load(f)
        except Exception as e:
            raise RuntimeError(
                "Vector store not found. "
                "Run build_vector_store.py then sql_schema_linker.py first."
            ) from e

        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    # ──────────────────────────────────────────────────────────────────────
    # Core retrieval
    # ──────────────────────────────────────────────────────────────────────

    def retrieve_similar_examples(self, query: str, k: int = 10):
        """Top-k most similar training examples via cosine similarity."""
        emb = self.model.encode([query], convert_to_numpy=True).astype(np.float32)
        self.faiss.normalize_L2(emb)
        _, indices = self.index.search(emb, k)
        return [self.mapping[i] for i in indices[0]]

    def _retrieve_by_class(self, query: str, complexity: str, k: int):
        """Retrieve top-k examples filtered to a specific complexity class."""
        # Over-fetch to ensure enough examples of the requested class
        candidates = self.retrieve_similar_examples(query, k * 4)
        filtered = [e for e in candidates if e.get("complexity") == complexity]
        return filtered[:k]

    def _diverse_retrieve(self, query: str, k: int):
        """
        Retrieve k examples ensuring at least 1 per complexity class.
        Used for the classification prompt so the LLM sees all three labels.
        """
        candidates = self.retrieve_similar_examples(query, k * 4)

        selected = []
        seen_classes = set()

        # First pass: one of each class
        for ex in candidates:
            cls = ex.get("complexity", "EASY")
            if cls not in seen_classes:
                selected.append(ex)
                seen_classes.add(cls)
            if len(seen_classes) == 3:
                break

        # Second pass: fill remaining slots with top similar
        for ex in candidates:
            if len(selected) >= k:
                break
            if ex not in selected:
                selected.append(ex)

        return selected[:k]

    # ──────────────────────────────────────────────────────────────────────
    # Module 1 — Schema Linking
    # ──────────────────────────────────────────────────────────────────────

    def build_schema_linking_prompt(self,
                                    target_question: str,
                                    db_schema_text:  str,
                                    k: int = 5) -> str:
        """
        Format per example (chain-of-thought):
            <DB schema>
            Q: "..."
            A: Let's think step by step. ...
            Schema_links: [...]
        """
        examples = self.retrieve_similar_examples(target_question, k)

        prompt  = "# Find the schema_links for generating SQL queries for each "
        prompt += "question based on the database schema and Foreign keys.\n\n"
        prompt += db_schema_text + "\n"

        for ex in examples:
            links = ex.get("schema_links", "[]")
            prompt += f'Q: "{ex["question"]}"\n'
            prompt += "A: Let's think step by step.\n"
            prompt += f"Schema_links: {links}\n\n"

        # Target (no answer yet)
        prompt += f'Q: "{target_question}"\n'
        prompt += "A: Let's think step by step.\n"
        return prompt

    # ──────────────────────────────────────────────────────────────────────
    # Module 2 — Classification & Decomposition
    # ──────────────────────────────────────────────────────────────────────

    def build_classification_prompt(self,
                                    target_question: str,
                                    schema_links:    str,
                                    db_schema_text:  str,
                                    k: int = 5) -> str:
        """
        Format per example:
            Q: "..."
            schema_links: [...]
            A: Let's think step by step. ... Label: "EASY"
        """
        examples = self._diverse_retrieve(target_question, k)

        prompt  = "# For the given question, classify it as EASY, NON-NESTED, or NESTED "
        prompt += "based on nested queries and JOIN.\n"
        prompt += "if need nested queries: predict NESTED\n"
        prompt += "elif need JOIN and don't need nested queries: predict NON-NESTED\n"
        prompt += "elif don't need JOIN and don't need nested queries: predict EASY\n\n"
        prompt += db_schema_text + "\n"

        for ex in examples:
            links = ex.get("schema_links", "[]")
            cls   = ex.get("complexity", "EASY")
            prompt += f'Q: "{ex["question"]}"\n'
            prompt += f'schema_links: {links}\n'
            prompt += f"A: Let's think step by step. Label: \"{cls}\"\n\n"

        # Target
        prompt += f'Q: "{target_question}"\n'
        prompt += f'schema_links: {schema_links}\n'
        prompt += "A: Let's think step by step."
        return prompt

    # ──────────────────────────────────────────────────────────────────────
    # Module 3a — SQL Generation: EASY
    # ──────────────────────────────────────────────────────────────────────

    def build_easy_sql_prompt(self,
                              target_question: str,
                              schema_links:    str,
                              db_schema_text:  str,
                              k: int = 5) -> str:
        """
        Format: <Q, Schema_links, SQL>  — no intermediate representation.
        """
        examples = self._retrieve_by_class(target_question, "EASY", k)

        prompt  = "# Use the schema links to generate the SQL queries for each question.\n"
        prompt += db_schema_text + "\n\n"

        for ex in examples:
            links = ex.get("schema_links", "[]")
            prompt += f'Q: "{ex["question"]}"\n'
            prompt += f'Schema_links: {links}\n'
            prompt += f'SQL: {ex["query"]}\n\n'

        # Target
        prompt += f'Q: "{target_question}"\n'
        prompt += f'Schema_links: {schema_links}\n'
        prompt += "SQL:"
        return prompt

    # ──────────────────────────────────────────────────────────────────────
    # Module 3b — SQL Generation: NON-NESTED
    # ──────────────────────────────────────────────────────────────────────

    def build_non_nested_sql_prompt(self,
                                    target_question: str,
                                    schema_links:    str,
                                    db_schema_text:  str,
                                    k: int = 5) -> str:
        """
        Format: <Q, Schema_links, NatSQL intermediate rep, SQL>
        Uses chain-of-thought: "we need to join these tables = [...]"
        """
        examples = self._retrieve_by_class(target_question, "NON-NESTED", k)

        prompt  = "# Use the schema links and Intermediate_representation to generate SQL.\n"
        prompt += db_schema_text + "\n\n"

        for ex in examples:
            links = ex.get("schema_links", "[]")
            prompt += f'Q: "{ex["question"]}"\n'
            prompt += f'Schema_links: {links}\n'
            prompt += "A: Let's think step by step. "
            prompt += "For creating the SQL for the given question, "
            prompt += "we need to join the relevant tables.\n"
            prompt += f'SQL: {ex["query"]}\n\n'

        # Target
        prompt += f'Q: "{target_question}"\n'
        prompt += f'Schema_links: {schema_links}\n'
        prompt += "A: Let's think step by step."
        return prompt

    # ──────────────────────────────────────────────────────────────────────
    # Module 3c — SQL Generation: NESTED
    # ──────────────────────────────────────────────────────────────────────

    def build_nested_sql_prompt(self,
                                target_question: str,
                                schema_links:    str,
                                sub_questions:   str,
                                db_schema_text:  str,
                                k: int = 5) -> str:
        """
        Format: <Q, Schema_links, sub-question answers, NatSQL IR, SQL>
        First solves sub-questions, then builds the final query.
        """
        examples = self._retrieve_by_class(target_question, "NESTED", k)

        prompt  = "# Use the intermediate representation and schema links to generate SQL.\n"
        prompt += db_schema_text + "\n\n"

        for ex in examples:
            links = ex.get("schema_links", "[]")
            prompt += f'Q: "{ex["question"]}"\n'
            prompt += f'Schema_links: {links}\n'
            prompt += "A: Let's think step by step. "
            prompt += f'This can be solved by first answering the sub-question.\n'
            prompt += f'SQL: {ex["query"]}\n\n'

        # Target — partial prompt, LLM completes from here
        prompt += f'Q: "{target_question}"\n'
        prompt += f'Schema_links: {schema_links}\n'
        prompt += f'Sub-questions: "{sub_questions}"\n'
        prompt += "A: Let's think step by step.\n"
        prompt += f'The SQL query for the sub-question "'
        return prompt

    # ──────────────────────────────────────────────────────────────────────
    # Module 4 — Self-Correction (gentle variant, best for GPT-4)
    # ──────────────────────────────────────────────────────────────────────

    def build_self_correction_prompt(self,
                                     target_question: str,
                                     sql:             str,
                                     db_schema_text:  str) -> str:
        """
        Zero-shot gentle self-correction.
        Does NOT assume the SQL is buggy — asks the model to check and fix if needed.
        """
        prompt  = "#### For the given question, use the provided tables, columns, "
        prompt += "and foreign keys to fix the SQLite SQL QUERY for any issues. "
        prompt += "If there are no issues, return the SQLite SQL QUERY as is.\n"
        prompt += "#### Use the following instructions for fixing the SQL QUERY:\n"
        prompt += "1) Use the database values that are explicitly mentioned in the question.\n"
        prompt += "2) Pay attention to the columns used for JOIN via Foreign_keys.\n"
        prompt += "3) Use DESC and DISTINCT when needed.\n"
        prompt += "4) Pay attention to the columns used for GROUP BY.\n"
        prompt += "5) Pay attention to the columns used for SELECT.\n"
        prompt += "6) Only change the GROUP BY clause when necessary.\n"
        prompt += "7) Use GROUP BY on one column only.\n\n"
        prompt += db_schema_text + "\n"
        prompt += f"#### Question: {target_question}\n"
        prompt += f"#### SQLite SQL QUERY\n{sql}\n"
        prompt += "#### SQLite FIXED SQL QUERY\nSELECT"
        return prompt
