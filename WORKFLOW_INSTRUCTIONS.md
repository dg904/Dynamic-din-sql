# Dynamic Demonstration Retrieval Workflow

This project extends DIN-SQL by choosing examples dynamically instead of using the same fixed examples for every question.

## Simple Idea

Imagine you ask a new English question and want SQL as the answer. Instead of showing the model random examples, we first search the Spider training set for old questions that sound similar. Those similar examples are placed into the prompt, so the model sees examples that are more relevant to the current question.

## The Final Implementation

The entire pipeline is unified into the `extended_DIN_SQL.py` script (which you updated as `extended_DIN_SQL_new.py`). This script handles everything end-to-end:
1. **Embedding**: Uses `SentenceTransformers` (all-MiniLM-L6-v2) to encode questions.
2. **Retrieval**: Uses `FAISS` to store vectors and retrieve the top-K nearest examples.
3. **Prompt Building**: Injects the retrieved examples dynamically into the prompt.
4. **LLM Generation**: Calls the NVIDIA NIM API to generate the SQL.
5. **Evaluation**: Compares generated SQL against the gold standard using Execution Accuracy (EX) and Exact Match (EM).

## Folder Setup

Put the Spider dataset inside this project like this:

```text
project root/
  spider/
    train_spider.json
    dev.json
    tables.json
    database/
      concert_singer/
        concert_singer.sqlite
      ...
  files/
    evaluator.py
    sql_schema_linker.py
    local_benchmark.py
  extended_DIN_SQL.py
```

## Installation

Use Python 3.10 or newer.

```bash
pip install -r requirements.txt
```

If `python` is not available on Windows, try:

```bash
py -m pip install -r requirements.txt
```

## Running the Pipeline

Run these commands from the project root folder. The script will automatically build the FAISS vector store on the first run if it doesn't exist.

**1. Set your NVIDIA API Key (PowerShell)**
```powershell
$env:NVIDIA_API_KEY="paste_nvidia_key_here"
```

**2. Test the connection / Build the Vector Store (No API calls yet)**
```powershell
python extended_DIN_SQL.py --prepare_only
```

**3. Run the benchmark (Validation Sample Size)**
```powershell
python extended_DIN_SQL.py --sample_size 50
```

**4. Run Full Evaluation**
```powershell
python extended_DIN_SQL.py --sample_size 1034
```
or 
python extended_DIN_SQL_new.py --spider_dir spider

## Outputs & Evaluation

After execution, the script generates output logs and metric reports in the `results/` folder:

- `results/extended_din_sql_results.json`: Full log of every query and status.
- `results/extended_din_sql_results.md`: A markdown summary of your exact match and execution accuracy metrics compared across difficulties.
- `results/extended_static_predictions.sql`: The predictions from the static baseline.
- `results/extended_dynamic_predictions.sql`: The predictions from your dynamic retrieval extension.

These metrics explicitly track performance on "Easy", "Medium", "Hard", and "Extra" difficulty levels to highlight where dynamic retrieval improves complex schema handling.
