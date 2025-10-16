# Reproducing Experimental Results (RAG SQL Rewriting on BigQuery)

This README explains how to reproduce the experimental results (per-query and parameter-wise tables) used in the dissertation, including FAISS setup, rewriting, evaluation, and aggregation. \
This repository provides the implementation and experiment pipeline for evaluating RAG-based SQL query rewriting on Google BigQuery. \
It reproduces two key result tables in the dissertation:

    1. Per-query performance table (equivalence and slot reduction per query)
    2. Condition-wise performance table (aggregated by topk and min_similarity)

## 0. Preparation
### Step 1: Register FAISS Index (29 Query Pairs)

```bash
python3 build_faiss_from_sheet_bq.py \
  --sheet "/home/hff1231/921_modified_queries.xlsx" \
  --sheet-name "Sheet1" \
  --artifacts-dir "/home/hff1231/artifacts" \
  --plans-dir "/home/hff1231/artifacts/plans_dump" \
  --project "useful-autumn-459411-g9" \
  --append
```

### Step 2: Retrieve Example Query Plans (Optional)

```bash
python3 sql2planjson.py --sql ~/queries_example/q3/orig.sql  --out /tmp/q3_plan.json
python3 sql2planjson.py --sql ~/queries_example/q6/orig.sql  --out /tmp/q6_plan.json
python3 sql2planjson.py --sql ~/queries_example/q14/orig.sql --out /tmp/q14_plan.json
python3 sql2planjson.py --sql ~/queries_example/q9/orig.sql  --out /tmp/q9_plan.json
python3 sql2planjson.py --sql ~/queries_example/q21/orig.sql --out /tmp/q21_plan.json
```

### Step 3: Generate Rewritten Queries (RAG / Zero-shot)

```bash
python3 ~/run_rewrite_batch.py \
  --rewrite_script  ./query_rewrite_v3_faiss_temp0.py \
  --artifacts_dir   ~/artifacts \
  --mapping_json    /tmp/mapping.json \
  --model           gpt-4o-mini \
  --topk            5 \
  --min_similarity  0.10
```

## 1. Run the Evaluation (Raw Data Collection)

Each experiment runs all query variants on BigQuery multiple times (e.g., 5 runs). \
It collects total slot time, bytes processed, and checks equivalence between variants.

```bash
PROJECT_ID="useful-autumn-459411-g9"
LOCATION="asia-northeast1"

cat > /tmp/experiment_config.json <<EOF
{
  "project_id": "$PROJECT_ID",
  "location_default": "$LOCATION",
  "query_sets": [
    {
      "id": "q3",
      "name": "Query 3: Shipping Priority",
      "ordered": true,
      "order_by": "revenue DESC, o_orderdate",
      "sql_paths": {
        "orig": "/home/hff1231/queries_example/q3/orig.sql",
        "zero": "/home/hff1231/queries_example/q3/zero.sql",
        "rag":  "/home/hff1231/queries_example/q3/rag.sql"
      }
    },
    ...
  ]
}
EOF

python3 /home/hff1231/bq_cost_eval.py \
  --config /tmp/experiment_config.json \
  --out /tmp/bq_eval_results_topk5_sim010_runs5.csv \
  --runs 5 \
  --tolerance 1e-9
```

Output: /tmp/bq_eval_results_topk5_sim010_runs5.csv \
This file serves as the base input for the next summarization scripts.
