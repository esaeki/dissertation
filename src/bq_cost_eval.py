#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bq_cost_eval.py  (RAG / Zero equivalence + approximate set comparison + N-run median)

- Execute three variants on BigQuery: orig / zero / rag (cache disabled)
- Measure execution metrics (slot_millis / total_bytes_processed) N times (--runs) and take the median
- Equivalence:
  - ordered=true  : Let BigQuery sort with the specified order_by and compare rowwise approximately (±tol)
  - ordered=false : Judge by approximate multiset equality (±tol, including duplicates)
- CSV output: save each variant's median + deltas + equivalence flags
"""

from __future__ import annotations
import argparse
import csv
import json
import math
import os
import re
from statistics import median
from typing import Any, Dict, List, Tuple

from google.cloud import bigquery

# ----------------------------
# Utilities
# ----------------------------

def read_sql(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()
    # Remove trailing semicolon
    return re.sub(r";\s*$", "", sql.strip(), flags=re.S)

def bq_run_query(client: bigquery.Client, sql: str, location: str, job_label: str) -> Tuple[List[bigquery.table.Row], Dict[str, Any]]:
    job_config = bigquery.QueryJobConfig(
        use_query_cache=False,  # ★ Disable cache
        labels={"eval": "cost", "run": job_label.replace("/", "_")[:60]}
    )
    job = client.query(sql, job_config=job_config, location=location)
    rows = list(job.result())
    metrics = {
        "slot_millis": getattr(job, "slot_millis", None),
        "total_bytes_processed": getattr(job, "total_bytes_processed", None),
    }
    return rows, metrics

def run_variant_many(client, sql, location, label, runs: int) -> Tuple[List[bigquery.table.Row], List[int], List[int]]:
    """
    Execute the same SQL 'runs' times.
    - rows: rows from the 1st run (used for equivalence checks)
    - slot_millis_list / bytes_list: per-run metrics (None → 0)
    """
    rows_first: List[bigquery.table.Row] = []
    slot_list: List[int] = []
    byte_list: List[int] = []
    for i in range(runs):
        rows, met = bq_run_query(client, sql, location, f"{label}_r{i+1}")
        if i == 0:
            rows_first = rows
        slot_list.append(0 if met["slot_millis"] is None else int(met["slot_millis"]))
        byte_list.append(0 if met["total_bytes_processed"] is None else int(met["total_bytes_processed"]))
    return rows_first, slot_list, byte_list

# ===== Approximate comparison (set/multiset) =====

def digits_from_tol(tol: float) -> int:
    if tol <= 0:
        return 9
    return max(0, int(round(-math.log10(tol))))

def normalize_cell_approx(v: Any, tol: float) -> Tuple[str, Any]:
    """Numbers are rounded; arrays/dicts are serialized; others are left as-is."""
    if v is None:
        return ("__NONE__", None)
    # Serialize list/dict (stabilize order/keys)
    if isinstance(v, (list, dict)):
        return ("__JSON__", json.dumps(v, sort_keys=True, ensure_ascii=False))
    # Approximate numeric
    try:
        x = float(v)
        d = digits_from_tol(tol)
        return ("__NUM__", round(x, d))
    except Exception:
        return ("__RAW__", v)

def normalize_row_approx(row: bigquery.table.Row, tol: float) -> Tuple:
    return tuple(normalize_cell_approx(v, tol) for v in row.values())

def are_sets_equal_approx(rows_a: List[bigquery.table.Row], rows_b: List[bigquery.table.Row], tol: float = 1e-9) -> bool:
    """Order-insensitive + duplicate counting + approximate comparison."""
    from collections import Counter
    ca = Counter(normalize_row_approx(r, tol) for r in rows_a)
    cb = Counter(normalize_row_approx(r, tol) for r in rows_b)
    return ca == cb

# ===== Approximate comparison (rowwise with order) =====

def approx_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    try:
        if a is None and b is None:
            return True
        if (a is None) != (b is None):
            return False
        ax = float(a); bx = float(b)
        return abs(ax - bx) <= tol
    except Exception:
        return a == b

def are_rows_equal_rowwise(rows_a: List[bigquery.table.Row], rows_b: List[bigquery.table.Row], tol: float = 1e-9) -> bool:
    if len(rows_a) != len(rows_b):
        return False
    for ra, rb in zip(rows_a, rows_b):
        if list(ra.keys()) != list(rb.keys()):
            return False
        for key in ra.keys():
            if not approx_equal(ra[key], rb[key], tol):
                return False
    return True

def fetch_ordered_rows(client: bigquery.Client, base_sql: str, order_by: str, location: str, label: str) -> List[bigquery.table.Row]:
    wrapped = f"SELECT * FROM ({base_sql}) ORDER BY {order_by}"
    rows, _ = bq_run_query(client, wrapped, location, f"{label}_ordered")
    return rows

# ----------------------------
# Evaluate one query set
# ----------------------------

def eval_query_set(
    client: bigquery.Client,
    qid: str,
    name: str,
    ordered: bool,
    order_by: str | None,
    paths: Dict[str, str],
    location_default: str,
    runs: int,
    tol: float,
) -> Dict[str, Any]:
    sql_orig = read_sql(paths["orig"])
    sql_zero = read_sql(paths["zero"])
    sql_rag  = read_sql(paths["rag"])

    print(f"\n== {name} ({qid}) ==")

    # Execute N times (rows are from the 1st run)
    rows_o, slots_o, bytes_o = run_variant_many(client, sql_orig, location_default, f"{qid}_orig", runs)
    rows_z, slots_z, bytes_z = run_variant_many(client, sql_zero, location_default, f"{qid}_zero", runs)
    rows_r, slots_r, bytes_r = run_variant_many(client, sql_rag,  location_default, f"{qid}_rag",  runs)

    # Equivalence: when ordered, re-fetch once with ORDER BY on BigQuery side
    if ordered and order_by:
        rows_o_ord = fetch_ordered_rows(client, sql_orig, order_by, location_default, f"{qid}_orig")
        rows_z_ord = fetch_ordered_rows(client, sql_zero, order_by, location_default, f"{qid}_zero")
        rows_r_ord = fetch_ordered_rows(client, sql_rag,  order_by, location_default, f"{qid}_rag")

        equiv_orig_vs_rag  = are_rows_equal_rowwise(rows_o_ord, rows_r_ord, tol=tol)
        equiv_orig_vs_zero = are_rows_equal_rowwise(rows_o_ord, rows_z_ord, tol=tol)
    else:
        equiv_orig_vs_rag  = are_sets_equal_approx(rows_o, rows_r, tol=tol)
        equiv_orig_vs_zero = are_sets_equal_approx(rows_o, rows_z, tol=tol)

    # Medians
    slot_o_med = int(median(slots_o))
    slot_z_med = int(median(slots_z))
    slot_r_med = int(median(slots_r))
    byt_o_med  = int(median(bytes_o))
    byt_z_med  = int(median(bytes_z))
    byt_r_med  = int(median(bytes_r))

    # Deltas (median vs median)
    d_slot_o2r = slot_o_med - slot_r_med
    d_slot_o2z = slot_o_med - slot_z_med
    d_bytes_o2r = byt_o_med - byt_r_med
    d_bytes_o2z = byt_o_med - byt_z_med

    # Console output (more explicit)
    def _fmt(n: int) -> str:
        return f"{n:,}"

    print(f"Equivalence (orig vs rag) : {'OK' if equiv_orig_vs_rag else 'MISMATCH'}")
    print(f"Equivalence (orig vs zero): {'OK' if equiv_orig_vs_zero else 'MISMATCH'}")

    print(f"\nMedians over {runs} runs")
    print(f"  Slot [ms] : orig={_fmt(slot_o_med)}, zero={_fmt(slot_z_med)}, rag={_fmt(slot_r_med)}")
    print(f"  Bytes     : orig={_fmt(byt_o_med)},  zero={_fmt(byt_z_med)},  rag={_fmt(byt_r_med)}")

    print("\nReductions (median vs median)")
    print(f"  Slot  Δ (orig→rag):  {_fmt(d_slot_o2r)} ms")
    print(f"  Slot  Δ (orig→zero): {_fmt(d_slot_o2z)} ms")
    print(f"  Bytes Δ (orig→rag):  {_fmt(d_bytes_o2r)}")
    print(f"  Bytes Δ (orig→zero): {_fmt(d_bytes_o2z)}")

    return {
        "qid": qid,
        "name": name,
        "ordered": ordered,
        "order_by": order_by or "",
        "runs": runs,
        "tolerance": tol,
        "equiv_orig_vs_rag": equiv_orig_vs_rag,
        "equiv_orig_vs_zero": equiv_orig_vs_zero,
        "slot_ms_orig_median": slot_o_med,
        "slot_ms_zero_median": slot_z_med,
        "slot_ms_rag_median":  slot_r_med,
        "bytes_orig_median": byt_o_med,
        "bytes_zero_median": byt_z_med,
        "bytes_rag_median":  byt_r_med,
        "delta_slot_orig_to_rag_median": d_slot_o2r,
        "delta_bytes_orig_to_rag_median": d_bytes_o2r,
        "delta_slot_orig_to_zero_median": d_slot_o2z,
        "delta_bytes_orig_to_zero_median": d_bytes_o2z,
    }

# ----------------------------
# Main
# ----------------------------

def main():
    parser = argparse.ArgumentParser(description="Evaluate BigQuery cost & equivalence (orig/zero/rag) with repeats & approx equality")
    parser.add_argument("--config", required=True, help="experiment_config.json")
    parser.add_argument("--out", required=True, help="output CSV path")
    parser.add_argument("--runs", type=int, default=5, help="repeat runs per variant (default: 5)")
    parser.add_argument("--tolerance", type=float, default=1e-9, help="numeric tolerance for equality (default: 1e-9)")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        conf = json.load(f)

    project_id = conf["project_id"]
    location_default = conf.get("location_default", "US")
    query_sets = conf["query_sets"]

    client = bigquery.Client(project=project_id)

    rows_out: List[Dict[str, Any]] = []

    for q in query_sets:
        qid = q["id"]
        name = q["name"]
        ordered = bool(q.get("ordered", False))
        order_by = q.get("order_by")
        paths = q["sql_paths"]

        result = eval_query_set(
            client=client,
            qid=qid,
            name=name,
            ordered=ordered,
            order_by=order_by,
            paths=paths,
            location_default=location_default,
            runs=max(1, int(args.runs)),
            tol=float(args.tolerance),
        )
        rows_out.append(result)

    fieldnames = [
        "qid","name","ordered","order_by","runs","tolerance",
        "equiv_orig_vs_rag","equiv_orig_vs_zero",
        "slot_ms_orig_median","slot_ms_zero_median","slot_ms_rag_median",
        "bytes_orig_median","bytes_zero_median","bytes_rag_median",
        "delta_slot_orig_to_rag_median","delta_bytes_orig_to_rag_median",
        "delta_slot_orig_to_zero_median","delta_bytes_orig_to_zero_median",
    ]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as wf:
        w = csv.DictWriter(wf, fieldnames=fieldnames)
        w.writeheader()
        for r in rows_out:
            w.writerow(r)

    print(f"\nDone. Wrote CSV to {args.out}")

if __name__ == "__main__":
    main()
