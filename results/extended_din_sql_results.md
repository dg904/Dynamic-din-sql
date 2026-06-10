# Extended DIN-SQL Results

Sanitized report: no API keys or local machine paths are included.

Dataset: Spider dev sample (50 questions)
Embedding retrieval: all-MiniLM-L6-v2 + FAISS
LLM: NVIDIA NIM meta/llama-3.3-70b-instruct
Mode: benchmark

## Overall Results

| Method | Samples | Completed | EX | EM | EX Completed Only | EM Completed Only | Avg Latency Sec |
|---|---:|---:|---:|---:|---:|---:|---:|
| Static fixed examples | 50 | 50 | 74.0 | 34.0 | 74.0 | 34.0 | 6.342 |
| Dynamic FAISS retrieval | 50 | 50 | 68.0 | 32.0 | 68.0 | 32.0 | 3.795 |

## Dynamic Retrieval By Difficulty

| Difficulty | Samples | EX | EM |
|---|---:|---:|---:|
| easy | 12 | 91.67 | 75.0 |
| medium | 13 | 76.92 | 23.08 |
| hard | 12 | 66.67 | 16.67 |
| extra | 13 | 38.46 | 15.38 |

## Notes

- All API calls go exclusively to NVIDIA NIM.
- Use a larger sample or the full dev set only after the 50-question run is stable.
