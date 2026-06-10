# Run Extended DIN-SQL

This project is ready to run with:

- FAISS retrieval
- SentenceTransformer embeddings
- NVIDIA NIM as the primary LLM
- `sample_size=50` default validation run

No API keys are stored in code. Set keys only in your terminal or create a .env file containing the NVIDIA_API_KEY in the same folder.

## 1. Set API Keys

PowerShell:

```powershell
$env:NVIDIA_API_KEY="paste_nvidia_key_here"
```

Optional model overrides:

```powershell
$env:NVIDIA_MODEL="meta/llama-3.3-70b-instruct"
```

By default, the embedding model loads from the local Hugging Face cache:

```powershell
$env:HF_LOCAL_FILES_ONLY="1"
```

If the embedding model is not cached yet and you want Python to download it, set:

```powershell
$env:HF_LOCAL_FILES_ONLY="0"
```

## 2. Prepare Without API Calls

Use this first. It builds or loads the FAISS vector store and confirms the pipeline is ready without calling NVIDIA NIM.

```powershell
python extended_DIN_SQL.py --sample_size 50 --prepare_only
```

If your normal `python` command is not available, use the bundled Python path or `py`.

## 3. Run 50-Sample Validation

```powershell
python extended_DIN_SQL.py --sample_size 50
or
python extended_DIN_SQL.py --spider_dir spider
```

Outputs:

```text
results/extended_din_sql_results.json
results/extended_din_sql_results.md
results/extended_static_predictions.sql
results/extended_dynamic_predictions.sql
```

## 4. Rebuild Vector Store If Needed

Only do this when changing the Spider dataset or schema-link extraction logic:

```powershell
python extended_DIN_SQL.py --sample_size 50 --rebuild_index --prepare_only
```

## 5. Full Dev Set Later

After the 50-sample run is stable and your API quota is enough:

```powershell
python extended_DIN_SQL.py --sample_size 1034
```

## Notes

- NVIDIA NIM is used for every question.
- Reports are sanitized and do not include API keys or local machine paths.
- If many calls fail with HTTP 429, the problem is quota/rate limits, not the retrieval code.
