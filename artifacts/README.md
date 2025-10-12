■ Reproducing the Results

This repository provides the implementation and experiment pipeline for evaluating RAG-based SQL query rewriting on Google BigQuery.
It reproduces two key result tables in the dissertation:

    1. Per-query performance table (equivalence and slot reduction per query)
    2. Condition-wise performance table (aggregated by topk and min_similarity)

■ Files and Their Roles

| Script                     | Input                                           | Output                                                 | Purpose                                                                                       |
| -------------------------- | ----------------------------------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| **`bq_cost_eval.py`**      | Experiment config (`experiment_config.json`)    | Raw execution logs (`bq_eval_results_*.csv`)           | Runs all queries (orig / zero / rag) on BigQuery, collects slot time and verifies equivalence |
| **`summarize_bq_eval.py`** | One CSV file from above                         | `bq_eval_summary.md` / `bq_eval_summary.csv`           | Generates the **per-query result table**                                                      |
| **`aggregate_results.py`** | Multiple CSVs from different parameter settings | `summary_by_condition.csv` / `summary_by_condition.md` | Produces the **parameter-level summary table** (e.g., `topk` × `min_similarity`)              |

Note: \
bq_cost_eval.py is required for both summary tables. \
summarize_bq_eval.py → query-level summary \
aggregate_results.py → parameter-level summary

0. Preparation \
Step 1: Register FAISS Index (29 Query Pairs)

```bash
python3 build_faiss_from_sheet_bq.py \
  --sheet "/home/hff1231/921_modified_queries.xlsx" \
  --sheet-name "Sheet1" \
  --artifacts-dir "/home/hff1231/artifacts" \
  --plans-dir "/home/hff1231/artifacts/plans_dump" \
  --project "useful-autumn-459411-g9" \
  --append
```

Step 2: Retrieve Example Query Plans (Optional)

```bash
python3 sql2planjson.py --sql ~/queries_example/q3/orig.sql  --out /tmp/q3_plan.json
python3 sql2planjson.py --sql ~/queries_example/q6/orig.sql  --out /tmp/q6_plan.json
python3 sql2planjson.py --sql ~/queries_example/q14/orig.sql --out /tmp/q14_plan.json
python3 sql2planjson.py --sql ~/queries_example/q9/orig.sql  --out /tmp/q9_plan.json
python3 sql2planjson.py --sql ~/queries_example/q21/orig.sql --out /tmp/q21_plan.json
```

Step 3: Generate Rewritten Queries (RAG / Zero-shot)

```bash
python3 ~/run_rewrite_batch.py \
  --rewrite_script  ./query_rewrite_v3_faiss_temp0.py \
  --artifacts_dir   ~/artifacts \
  --mapping_json    /tmp/mapping.json \
  --model           gpt-4o-mini \
  --topk            5 \
  --min_similarity  0.10
```

1. Run the Evaluation (Raw Data Collection)

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

2. Generate the Per-Query Summary Table

This step produces the table showing each query’s equivalence and slot reduction.
(Used for Section 5.4 of the dissertation.)

```bash
python3 summarize_bq_eval.py \
  --in /tmp/bq_eval_results_topk5_sim010_runs5.csv \
  --out_md /tmp/bq_eval_summary_topk5_sim010.md \
  --out_csv /tmp/bq_eval_summary_topk5_sim010.csv
```

Output columns:
- Query ID / Name
- Equivalence (orig vs rag, orig vs zero)
- Median slot time for each variant
- Slot reduction (orig → rag, zero → rag)
- Relative comparison (RAG better, Zero better, Tie)

3. Generate the Condition-wise Aggregated Table

After running multiple conditions (topk, min_similarity), aggregate them:

```bash
python3 /home/hff1231/aggregate_results.py \
  --inputs \
    /tmp/bq_eval_results_topk5_sim010_runs5.csv \
    /tmp/bq_eval_results_topk10_sim020_runs5.csv \
    /tmp/bq_eval_results_topk5_sim030_runs5.csv \
    /tmp/bq_eval_results_topk10_sim030_runs5.csv \
    /tmp/bq_eval_results_topk15_sim020_runs5.csv \
  --outdir /tmp/agg_out \
  --default_model gpt-4o-mini
```

Output:
- /tmp/agg_out/summary_by_condition.csv
- /tmp/agg_out/summary_by_condition.md

Columns include:
- topk, min_sim
- rag_best, zero_best, orig_best (count of fastest variants)
- equiv_rate_rag, equiv_rate_zero (equivalence ratio)
- median Δ(orig→rag), median Δ(zero→rag) (median slot difference)

Used for Section 5.5 “Parameter Sensitivity” in the dissertation.

4. Common Issues & Tips

| Issue                       | Cause / Fix                                                                 |
| --------------------------- | --------------------------------------------------------------------------- |
| **FAISS index not found**   | Check `--artifacts-dir` and file names like `faiss_v2_cosine.index`.        |
| **MISMATCH in equivalence** | Use reasonable `--tolerance` (e.g., 1e-9). Verify deterministic `ORDER BY`. |
| **Noisy slot time results** | Increase `--runs` to 3-5 and compute medians.                               |
| **BigQuery caching**        | Ensure cache is disabled (each run executes fresh).                         |

5. Mapping to Dissertation Tables

| Issue                       | Cause / Fix                                                                 |
| --------------------------- | --------------------------------------------------------------------------- |
| **FAISS index not found**   | Check `--artifacts-dir` and file names like `faiss_v2_cosine.index`.        |
| **MISMATCH in equivalence** | Use reasonable `--tolerance` (e.g., 1e-9). Verify deterministic `ORDER BY`. |
| **Noisy slot time results** | Increase `--runs` to 3-5 and compute medians.                               |
| **BigQuery caching**        | Ensure cache is disabled (each run executes fresh).                         |

■ Summary
- You need all three scripts to reproduce both tables.
- bq_cost_eval.py → runs experiments and stores raw metrics.
- summarize_bq_eval.py → creates the per-query table.
- aggregate_results.py → creates the parameter-level table.
