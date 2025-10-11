#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aggregate_results.py
- Combine multiple CSVs from bq_cost_eval.py (median-based, with equivalence flags)
- Parse condition metadata from filenames (e.g., bq_eval_results_topk5_sim030_runs5.csv)
  or from an optional JSON mapping file.
- Produce:
  1) combined_results.csv (row-per-query-per-condition with metadata)
  2) summary_by_condition.csv (counts of best variant, equivalence ok rates, medians)
  3) leaderboard_by_query.csv (best variant per query across conditions, margins)

Usage:
  python3 aggregate_results.py \
    --inputs /tmp/bq_eval_results_topk5_sim010_runs5.csv \
             /tmp/bq_eval_results_topk10_sim020_runs5.csv \
             /tmp/bq_eval_results_topk5_sim030_runs5.csv \
             /tmp/bq_eval_results_topk10_sim030_runs5.csv \
             /tmp/bq_eval_results_topk15_sim020_runs5.csv \
    --outdir /tmp/agg_out \
    --default_model gpt-4o-mini

Optional:
  --meta /path/to/conditions_meta.json
  (JSON example)
  {
    "bq_eval_results_topk5_sim010_runs5.csv": {"condition_id": "k5_s10", "topk": 5, "min_similarity": 0.10, "model": "gpt-4o-mini", "runs": 5},
    "any_name.csv": {"condition_id": "B1", "topk": 15, "min_similarity": 0.20, "model": "gpt-4o-mini", "runs": 5}
  }
"""
import argparse
import os
import re
import json
from pathlib import Path
from statistics import median

import pandas as pd

FNAME_PAT = re.compile(r".*topk(?P<topk>\d+).*sim(?P<sim>\d+).*?(?:runs(?P<runs>\d+))?.*\.csv$", re.I)

def infer_meta_from_filename(fname: str):
    """Infer topk / min_similarity / runs from filename tokens like topk10_sim020_runs5."""
    m = FNAME_PAT.match(os.path.basename(fname))
    if not m:
        return {}
    d = m.groupdict()
    meta = {}
    if d.get("topk") is not None:
        try:
            meta["topk"] = int(d["topk"])
        except Exception:
            pass
    if d.get("sim") is not None:
        s = d["sim"]
        try:
            # "030" -> 0.30, "010" -> 0.10, "000" -> 0.0
            meta["min_similarity"] = float(f"0.{s.lstrip('0')}" if s != "000" else "0.0")
        except Exception:
            pass
    if d.get("runs") is not None and d["runs"] is not None:
        try:
            meta["runs"] = int(d["runs"])
        except Exception:
            pass
    return meta

def load_meta_json(meta_path: str):
    if not meta_path:
        return {}
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)

def best_variant(row):
    """Pick the variant with minimal median slot_ms among orig/zero/rag; return (name, margin, dict)."""
    slots = {
        "orig": row.get("slot_ms_orig_median"),
        "zero": row.get("slot_ms_zero_median"),
        "rag" : row.get("slot_ms_rag_median"),
    }
    # None -> very large number to avoid winning
    norm = {k: (v if pd.notnull(v) else 10**18) for k, v in slots.items()}
    best = min(norm, key=norm.get)
    vals = sorted(norm.values())
    margin = vals[1] - vals[0] if len(vals) >= 2 else None
    return best, margin, slots

def rate_true(series: pd.Series):
    s = series.dropna()
    if len(s) == 0:
        return None
    return (s.astype(bool).sum() / len(s))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", required=True, help="one or more CSV files from bq_cost_eval.py")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--meta", default="", help="optional JSON mapping of filename -> metadata")
    ap.add_argument("--default_model", default="", help="fallback model name to attach if missing")
    args = ap.parse_args()

    Path(args.outdir).mkdir(parents=True, exist_ok=True)
    meta_map = load_meta_json(args.meta)

    frames = []
    for inp in args.inputs:
        df = pd.read_csv(inp)
        # add condition metadata
        meta = {"condition_id": os.path.basename(inp)}
        meta.update(infer_meta_from_filename(inp))
        meta.update(meta_map.get(os.path.basename(inp), {}))
        if args.default_model and "model" not in meta:
            meta["model"] = args.default_model
        for k, v in meta.items():
            df[k] = v
        frames.append(df)

    if not frames:
        raise SystemExit("No inputs read")

    all_df = pd.concat(frames, ignore_index=True)

    # normalize boolean-like columns
    for col in ["equiv_orig_vs_rag", "equiv_orig_vs_zero"]:
        if col in all_df.columns:
            if all_df[col].dtype == object:
                all_df[col] = all_df[col].astype(str).str.lower().isin(["true", "ok", "1", "yes"])
            else:
                all_df[col] = all_df[col].astype(bool)

    # best variant & margin per row
    bests, margins = [], []
    for _, row in all_df.iterrows():
        b, m, _ = best_variant(row)
        bests.append(b); margins.append(m)
    all_df["best_variant"] = bests
    all_df["best_margin_ms"] = margins

    # 1) combined
    combined_path = os.path.join(args.outdir, "combined_results.csv")
    all_df.to_csv(combined_path, index=False)

    # 2) summary by condition
    group_cols = [c for c in ["condition_id","topk","min_similarity","runs","model"] if c in all_df.columns]
    summ = (all_df
            .groupby(group_cols, dropna=False)
            .agg(
                n_queries=("qid","count"),
                rag_best=("best_variant", lambda s: (s=="rag").sum()),
                zero_best=("best_variant", lambda s: (s=="zero").sum()),
                orig_best=("best_variant", lambda s: (s=="orig").sum()),
                equiv_rate_rag=("equiv_orig_vs_rag", rate_true),
                equiv_rate_zero=("equiv_orig_vs_zero", rate_true),
                median_delta_o2r=("delta_slot_orig_to_rag_median","median"),
                median_delta_z2r=("delta_slot_zero_to_rag_median","median"),
            )
            .reset_index())
    summary_path = os.path.join(args.outdir, "summary_by_condition.csv")
    summ.to_csv(summary_path, index=False)

    # 3) leaderboard by query（各クエリで「最良マージンが大きい条件」を1行に）
    lb = (all_df
          .sort_values(["qid","best_margin_ms"], ascending=[True, False])
          .groupby("qid", as_index=False)
          .first()[["qid","name","condition_id","topk","min_similarity","runs","model","best_variant","best_margin_ms"]])
    leader_path = os.path.join(args.outdir, "leaderboard_by_query.csv")
    lb.to_csv(leader_path, index=False)

    print("Wrote:")
    print(" -", combined_path)
    print(" -", summary_path)
    print(" -", leader_path)

if __name__ == "__main__":
    main()
