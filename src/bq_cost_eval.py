#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bq_cost_eval.py  (RAG / Zero 等価性 + 近似集合比較 + N回実行メディアン)

- BigQuery で orig / zero / rag の3種を実行（キャッシュ無効）
- 実行メトリクス（slot_millis / total_bytes_processed）を N回（--runs）計測しメディアン採用
- 等価性:
  - ordered=true  : 指定 order_by で BigQuery 側に整列させ、行ごとに近似比較（±tol）
  - ordered=false : 近似集合等価（±tol, 重複まで一致）で判定
- CSV 出力: 各バリアントのメディアン + 差分 + 等価性を保存
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
# ユーティリティ
# ----------------------------

def read_sql(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()
    # 末尾セミコロンは除去
    return re.sub(r";\s*$", "", sql.strip(), flags=re.S)

def bq_run_query(client: bigquery.Client, sql: str, location: str, job_label: str) -> Tuple[List[bigquery.table.Row], Dict[str, Any]]:
    job_config = bigquery.QueryJobConfig(
        use_query_cache=False,  # ★ キャッシュ無効
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
    同一SQLを runs 回実行。
    - rows は 1回目の行（等価性検証に使用）
    - slot_millis_list / bytes_list は各回の数値（None→0 に丸め）
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

# ===== 近似比較（集合用） =====

def digits_from_tol(tol: float) -> int:
    if tol <= 0:
        return 9
    return max(0, int(round(-math.log10(tol))))

def normalize_cell_approx(v: Any, tol: float) -> Tuple[str, Any]:
    """数値は丸め、配列/辞書は整形、その他はそのまま。"""
    if v is None:
        return ("__NONE__", None)
    # list/dict は文字列化（順序/キー安定化）
    if isinstance(v, (list, dict)):
        return ("__JSON__", json.dumps(v, sort_keys=True, ensure_ascii=False))
    # 数値近似
    try:
        x = float(v)
        d = digits_from_tol(tol)
        return ("__NUM__", round(x, d))
    except Exception:
        return ("__RAW__", v)

def normalize_row_approx(row: bigquery.table.Row, tol: float) -> Tuple:
    return tuple(normalize_cell_approx(v, tol) for v in row.values())

def are_sets_equal_approx(rows_a: List[bigquery.table.Row], rows_b: List[bigquery.table.Row], tol: float = 1e-9) -> bool:
    """順序無視 + 重複カウント + 近似比較"""
    from collections import Counter
    ca = Counter(normalize_row_approx(r, tol) for r in rows_a)
    cb = Counter(normalize_row_approx(r, tol) for r in rows_b)
    return ca == cb

# ===== 近似比較（順序行ごと） =====

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
# 1クエリセットの評価
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

    # N回実行（rows は 1回目のもの）
    rows_o, slots_o, bytes_o = run_variant_many(client, sql_orig, location_default, f"{qid}_orig", runs)
    rows_z, slots_z, bytes_z = run_variant_many(client, sql_zero, location_default, f"{qid}_zero", runs)
    rows_r, slots_r, bytes_r = run_variant_many(client, sql_rag,  location_default, f"{qid}_rag",  runs)

    # 等価性：ordered は BigQuery 側で ORDER 付け直して1回取り直し
    if ordered and order_by:
        rows_o_ord = fetch_ordered_rows(client, sql_orig, order_by, location_default, f"{qid}_orig")
        rows_z_ord = fetch_ordered_rows(client, sql_zero, order_by, location_default, f"{qid}_zero")
        rows_r_ord = fetch_ordered_rows(client, sql_rag,  order_by, location_default, f"{qid}_rag")

        equiv_orig_vs_rag  = are_rows_equal_rowwise(rows_o_ord, rows_r_ord, tol=tol)
        equiv_orig_vs_zero = are_rows_equal_rowwise(rows_o_ord, rows_z_ord, tol=tol)
    else:
        equiv_orig_vs_rag  = are_sets_equal_approx(rows_o, rows_r, tol=tol)
        equiv_orig_vs_zero = are_sets_equal_approx(rows_o, rows_z, tol=tol)

    # メディアン
    slot_o_med = int(median(slots_o))
    slot_z_med = int(median(slots_z))
    slot_r_med = int(median(slots_r))
    byt_o_med  = int(median(bytes_o))
    byt_z_med  = int(median(bytes_z))
    byt_r_med  = int(median(bytes_r))

    # 差分（メディアン同士）
    d_slot_o2r = slot_o_med - slot_r_med
    d_slot_z2r = slot_z_med - slot_r_med
    d_bytes_o2r = byt_o_med - byt_r_med
    d_bytes_z2r = byt_z_med - byt_r_med

    # 画面表示
    print(f"Equivalence (orig vs rag) : {'OK' if equiv_orig_vs_rag else 'MISMATCH'}")
    print(f"Equivalence (orig vs zero): {'OK' if equiv_orig_vs_zero else 'MISMATCH'}")
    print(f"Slot reduction (orig→rag): {d_slot_o2r} ms   [medians over {runs} runs]")
    print(f"Slot reduction (zero→rag): {d_slot_z2r} ms   [medians over {runs} runs]")
    print(f"Bytes reduction (orig→rag): {d_bytes_o2r}")
    print(f"Bytes reduction (zero→rag): {d_bytes_z2r}")

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
        "delta_slot_zero_to_rag_median": d_slot_z2r,
        "delta_bytes_orig_to_rag_median": d_bytes_o2r,
        "delta_bytes_zero_to_rag_median": d_bytes_z2r,
    }

# ----------------------------
# メイン
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
        "delta_slot_orig_to_rag_median","delta_slot_zero_to_rag_median",
        "delta_bytes_orig_to_rag_median","delta_bytes_zero_to_rag_median",
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
