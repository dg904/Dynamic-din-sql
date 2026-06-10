# Dynamic DIN-SQL

> Asking a database a question in plain English — and actually getting the right answer.

This project extends the original [DIN-SQL](https://arxiv.org/abs/2308.15363) framework by swapping out its fixed, hand-picked prompt examples for ones that are *dynamically retrieved* based on what you're actually asking. Under the hood it uses FAISS to find the most similar training questions at runtime, then passes those as few-shot examples to an LLM (NVIDIA NIM) to generate the SQL. The result is noticeably better accuracy on complex, nested queries where static prompting tends to fall apart.

Benchmarked on the [Spider](https://yale-nlp.github.io/spider/) dataset.

---

## What's the difference from vanilla DIN-SQL?

The original DIN-SQL always uses the same fixed set of few-shot examples regardless of what question you ask. That works fine for simple queries, but for harder ones the examples are often irrelevant — so the model is flying blind.

This extension retrieves examples *similar to the current question* using semantic search (SentenceTransformers + FAISS). If you ask something about multi-table joins, you get join examples. If your question is nested, you get nested examples. The prompt becomes contextually relevant every single time.

---

## How it works

```
Your question
     │
     ▼
SentenceTransformer encodes it
     │
     ▼
FAISS finds the k most similar training questions
     │
     ▼
Those become few-shot examples in the prompt
     │
     ▼
NVIDIA NIM (Llama 3.3 70B) generates the SQL
     │
     ▼
SQL is executed and evaluated against Spider gold queries
```

---

## Project structure

```
Dynamic-din-sql/
├── extended_DIN_SQL.py        # Main pipeline script
├── files/
│   ├── evaluator.py           # Execution accuracy + exact match scoring
│   └── sql_schema_linker.py   # Schema link extraction
├── spider/                    # Spider dataset (train, dev, tables, databases)
├── vector_store/              # FAISS index + mapping (auto-built on first run)
├── results/                   # Output predictions and reports
├── requirements.txt
├── RUN_EXTENDED_DIN_SQL.md    # Step-by-step run guide
└── DIN_SQL_vs Our_Extension.pdf   # Results comparison writeup
```

---

## Setup

**1. Clone and install dependencies**

```bash
git clone https://github.com/dg904/Dynamic-din-sql.git
cd Dynamic-din-sql
pip install -r requirements.txt
```

**2. Get the Spider dataset**

Download from [the official Spider page](https://yale-nlp.github.io/spider/) and place it in the `spider/` folder. You need `train_spider.json`, `dev.json`, `tables.json`, and the `database/` folder.

**3. Get an NVIDIA NIM API key**

Free tier available at [build.nvidia.com](https://build.nvidia.com). Create a `.env` file in the project root:

```
NVIDIA_API_KEY=nvapi-xxxx
```

---

## Running it

**First run — build the vector store without making any API calls:**

```bash
python extended_DIN_SQL.py --prepare_only
```

This builds the FAISS index from the Spider training set. Takes a minute, only needed once.

**Run the 50-question benchmark:**

```bash
python extended_DIN_SQL.py --sample_size 50
```

**Test that your API key is working:**

```bash
python extended_DIN_SQL.py --test_api
```

**Run on the full Spider dev set (1034 questions):**

```bash
python extended_DIN_SQL.py --sample_size 1034
```

---

## Output

After a run, results land in `results/`:

| File | What's in it |
|---|---|
| `extended_din_sql_results.json` | Full results with per-question details |
| `extended_din_sql_results.md` | Human-readable summary table |
| `extended_static_predictions.sql` | SQL predictions using static examples |
| `extended_dynamic_predictions.sql` | SQL predictions using dynamic retrieval |

Reports are sanitized — no API keys or local paths are stored.

---

## CLI options

| Flag | Default | Description |
|---|---|---|
| `--spider_dir` | `spider` | Path to the Spider dataset |
| `--sample_size` | `50` | Number of dev questions to evaluate |
| `--k` | `5` | Number of few-shot examples to retrieve |
| `--vector_dir` | `vector_store` | Where to save/load the FAISS index |
| `--rebuild_index` | off | Force-rebuild the vector store |
| `--prepare_only` | off | Build index only, no API calls |
| `--test_api` | off | Smoke-test NVIDIA connectivity and exit |

---

## Tips

- If you see `HTTP 429` errors, you've hit the NVIDIA NIM rate limit. Wait a minute and re-run — the pipeline resumes without losing prior results.
- The embedding model (`all-MiniLM-L6-v2`) loads from the local Hugging Face cache by default. Set `HF_LOCAL_FILES_ONLY=0` the first time if it hasn't been downloaded yet.
- Rebuilding the index is only necessary if you change the training data or schema linking logic.

---

## Paper & comparison

A detailed comparison between the original DIN-SQL and this extension is included as `DIN_SQL_vs Our_Extension.pdf`. The project paper is at `Project paper.pdf`.

---

## Requirements

- Python 3.9+
- `faiss-cpu`, `sentence-transformers`, `requests`, `numpy`
- Spider dataset
- NVIDIA NIM API key (free tier)
