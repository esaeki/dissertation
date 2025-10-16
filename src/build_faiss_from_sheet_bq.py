#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
build_faiss_from_sheet_bq.py
- Purpose: From an Excel/CSV list of query pairs, extract features from the raw query's execution plan and register them to FAISS (for RAG retrieval).
- Characteristics:
  * Fix BigQuery job retrieval --location to asia-northeast1 (mandatory)
  * If job retrieval fails, fall back to EXPLAIN <raw_sql> to obtain the execution plan
  * v2 features (same 17 dims as register_to_faiss_v2) → StandardScaler → L2 → IndexFlatIP (cosine)
  * If existing index/metadata exist, append; otherwise create new
- Required artifacts (under --artifacts-dir):
  * scaler_v2.pkl
  * feature_schema_v2.json
  * (when appending) faiss_v2_cosine.index, metadata_v2.parquet

- REQUIRED sheet columns (must exist exactly):
  * category
  * raw_query
  * raw_query_id
  * optimized_query
  * optimized_query_id
"""

import os
import re
import json
import uuid
import argparse
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import faiss
import joblib
from google.cloud import bigquery

# ---------- Constants ----------
JOB_LOCATION = "asia-northeast1"  # unified location
FAISS_INDEX_NAME = "faiss_v2_cosine.index"
SCALER_NAME = "scaler_v2.pkl"
METADATA_PARQUET = "metadata_v2.parquet"
FEATURE_SCHEMA_NAME = "feature_schema_v2.json"

# ---------- Utilities ----------
def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

def safe_get(d: Dict[str, Any], path: List[str], default=0):
    cur = d
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur

def l2_normalize(a: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(a, axis=1, keepdims=True) + 1e-12
    return a / n

def load_feature_keys(artifacts_dir: str) -> List[str]:
    p = os.path.join(artifacts_dir, FEATURE_SCHEMA_NAME)
    with open(p, "r", encoding="utf-8") as f:
        sch = json.load(f)
    return sch.get("keys") or sch.get("feature_keys") or sch["keys"]

# ---------- BigQuery retrieval ----------
def fetch_job_properties(client: bigquery.Client, job_id: str) -> Dict[str, Any]:
    """
    Retrieve BigQuery QueryJob with an explicit location and return _properties.
    """
    job = client.get_job(job_id, location=JOB_LOCATION)  # location must be specified
    # to_api_repr() is also fine, but _properties often contains richer plan info
    return job._properties  # type: ignore

def fetch_plan_via_explain(client: bigquery.Client, sql: str) -> Dict[str, Any]:
    """
    Run EXPLAIN <sql>, obtain explain_json, and stuff it into statistics.query pseudo-compatibly.
    """
    q = "EXPLAIN\n" + sql
    job = client.query(q, job_config=bigquery.QueryJobConfig(dry_run=False, use_query_cache=False), location=JOB_LOCATION)
    rows = list(job.result())
    if not rows:
        raise RuntimeError("EXPLAIN returned no rows")
    explain_json_str = rows[0].get("explain_json") if "explain_json" in rows[0] else rows[0][0]
    explain = json.loads(explain_json_str)
    return {
        "statistics": {
            "query": {
                "text": sql,
                "queryPlan": explain.get("queryPlan", []),
                "totalBytesProcessed": explain.get("totalBytesProcessed", 0),
                "totalSlotMs": explain.get("totalSlotMs", 0),
            }
        }
    }

def extract_sql_from_props(props: Dict[str, Any]) -> str:
    return (
        props.get("statistics", {}).get("query", {}).get("query", "")  # old field name
        or props.get("statistics", {}).get("query", {}).get("text", "")
        or ""
    )

# ---------- v2 features ----------
def summarize_plan_for_features(props: Dict[str, Any]) -> Dict[str, Any]:
    q = props.get("statistics", {}).get("query", {}) or {}
    stages = q.get("queryPlan", []) or []
    n_stages = len(stages)

    total_slot_ms = float(q.get("totalSlotMs", 0) or 0)
    total_bytes_proc = float(q.get("totalBytesProcessed", 0) or 0)

    stage_slot_ms: List[float] = []
    bytes_read = 0.0
    bytes_written = 0.0
    rec_read = 0.0
    rec_written = 0.0
    n_joins = 0
    n_sorts = 0
    n_aggs = 0

    for st in stages:
        sm = float(st.get("slotMs", 0) or 0)
        stage_slot_ms.append(sm)

        display = (st.get("displayName") or "")
        steps = st.get("steps", []) or []
        steps_txt = []
        for s in steps:
            kind = s.get("kind", "")
            subs = s.get("substeps", [])
            if isinstance(subs, list) and subs:
                steps_txt.append(kind + " " + " ".join(map(str, subs)))
            else:
                steps_txt.append(kind)
        text = (display + " " + " ".join(steps_txt)).lower()
        if "join" in text: n_joins += 1
        if "sort" in text or "order" in text: n_sorts += 1
        if "aggregate" in text or "agg" in text or "group by" in text: n_aggs += 1

        bytes_read     += float(safe_get(st, ["read", "bytesRead"], 0) or 0)
        bytes_written  += float(safe_get(st, ["write", "bytesWritten"], 0) or 0)
        rec_read       += float(safe_get(st, ["read", "recordsRead"], 0) or 0)
        rec_written    += float(safe_get(st, ["write", "recordsWritten"], 0) or 0)

    if not stage_slot_ms and total_slot_ms > 0:
        stage_slot_ms = [total_slot_ms]
    if bytes_read == 0 and total_bytes_proc > 0:
        bytes_read = total_bytes_proc

    avg_slot_ms = float(np.mean(stage_slot_ms)) if stage_slot_ms else 0.0
    p95_slot_ms = float(np.percentile(stage_slot_ms, 95)) if stage_slot_ms else 0.0

    return {
        "n_stages": float(n_stages),
        "n_joins": float(n_joins),
        "n_sorts": float(n_sorts),
        "n_aggregations": float(n_aggs),
        "total_slot_ms": float(total_slot_ms),
        "avg_slot_ms": float(avg_slot_ms),
        "p95_slot_ms": float(p95_slot_ms),
        "bytes_read_total": float(bytes_read),
        "bytes_written_total": float(bytes_written),
        "records_read_total": float(rec_read),
        "records_written_total": float(rec_written),
    }

def basic_sql_stats(sql: str) -> Dict[str, Any]:
    s = (sql or "").lower()
    select_cols = s.count(",") + (1 if "select" in s else 0)
    where_pred  = s.count(" where ")
    group_by    = s.count(" group by ")
    order_by    = s.count(" order by ")
    joins       = s.count(" join ")
    return {
        "select_columns_count": float(max(select_cols, 0)),
        "where_predicates_count": float(max(where_pred, 0)),
        "groupby_cols": float(max(group_by, 0)),
        "orderby_cols": float(max(order_by, 0)),
        "sql_joins_count": float(max(joins, 0)),
    }

def build_features_v2(props: Dict[str, Any], raw_sql: str, schema_keys: List[str]) -> np.ndarray:
    pj = summarize_plan_for_features(props)
    sj = basic_sql_stats(raw_sql or "")

    read_write_ratio = pj["bytes_read_total"] / (pj["bytes_written_total"] + 1.0)
    heavy_ops_density = (
        (pj["n_joins"] + pj["n_sorts"] + pj["n_aggregations"]) / pj["n_stages"]
        if pj["n_stages"] > 0 else 0.0
    )

    feat_map = {
        "n_stages": pj["n_stages"],
        "n_joins": pj["n_joins"],
        "n_sorts": pj["n_sorts"],
        "n_aggregations": pj["n_aggregations"],
        "avg_slot_ms": pj["avg_slot_ms"],
        "p95_slot_ms": pj["p95_slot_ms"],
        "bytes_read_total": pj["bytes_read_total"],
        "bytes_written_total": pj["bytes_written_total"],
        "records_read_total": pj["records_read_total"],
        "records_written_total": pj["records_written_total"],
        "read_write_ratio": float(read_write_ratio),
        "heavy_ops_density": float(heavy_ops_density),
        "select_columns_count": sj["select_columns_count"],
        "where_predicates_count": sj["where_predicates_count"],
        "groupby_cols": sj["groupby_cols"],
        "orderby_cols": sj["orderby_cols"],
        "sql_joins_count": sj["sql_joins_count"],
    }

    missing = [k for k in schema_keys if k not in feat_map]
    if missing:
        raise SystemExit(f"feature mismatch against schema: missing={missing}")

    vec = np.array([[float(feat_map[k]) for k in schema_keys]], dtype=np.float32)
    return vec

# ---------- Metadata / FAISS ----------
def load_existing_index_meta(artifacts_dir: str):
    idx_path = os.path.join(artifacts_dir, FAISS_INDEX_NAME)
    meta_path = os.path.join(artifacts_dir, METADATA_PARQUET)
    index = None
    meta_df = None
    if os.path.exists(idx_path) and os.path.exists(meta_path):
        index = faiss.read_index(idx_path)
        meta_df = pq.read_table(meta_path).to_pandas()
    return index, meta_df

def append_metadata(meta_path: str, df_append: pd.DataFrame):
    if os.path.exists(meta_path):
        base = pq.read_table(meta_path)
        out = pa.Table.from_pandas(pd.concat([base.to_pandas(), df_append], ignore_index=True))
    else:
        out = pa.Table.from_pandas(df_append)
    pq.write_table(out, meta_path)

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description="Build/append FAISS from sheet + BigQuery plans.")
    ap.add_argument("--sheet", required=True, help="Path to Excel/CSV")
    ap.add_argument("--sheet-name", default=None, help="Excel sheet name (if Excel)")
    ap.add_argument("--artifacts-dir", required=True)
    ap.add_argument("--plans-dir", default=None, help="Optional: dump fetched plans as JSON")
    ap.add_argument("--project", required=True)
    ap.add_argument("--append", action="store_true", help="Append to existing index/metadata if present")
    args = ap.parse_args()

    ensure_dir(args.artifacts_dir)
    if args.plans_dir:
        ensure_dir(args.plans_dir)

    # Load (auto-detect Excel/CSV)
    if args.sheet.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(args.sheet, sheet_name=args.sheet_name)
    else:
        df = pd.read_csv(args.sheet)
    df.columns = [str(c).strip() for c in df.columns]

    # REQUIRED columns
    required_cols = ["category", "raw_query", "raw_query_id", "optimized_query", "optimized_query_id"]
    missing_required = [c for c in required_cols if c not in df.columns]
    if missing_required:
        raise SystemExit(f"ERROR: Required columns not found: {missing_required}\nColumns: {list(df.columns)}")

    # Artifacts
    scaler = joblib.load(os.path.join(args.artifacts_dir, SCALER_NAME))
    schema_keys = load_feature_keys(args.artifacts_dir)

    # Existing index/meta
    index, meta_df_existing = load_existing_index_meta(args.artifacts_dir)
    if index is None or not args.append:
        # Create new
        index = faiss.IndexFlatIP(len(schema_keys))
        meta_df_existing = pd.DataFrame(columns=[
            "id", "pair_id", "variant", "raw_job_id", "opt_job_id",
            "raw_sql_text", "opt_sql_text", "category"
        ])

    client = bigquery.Client(project=args.project, location=JOB_LOCATION)

    vecs = []
    new_meta_rows = []

    for i, r in df.iterrows():
        raw_job_id = str(r.get("raw_query_id") or "").strip()
        opt_sql = str(r.get("optimized_query") or "").strip()
        raw_sql_sheet = str(r.get("raw_query") or "").strip()
        category = str(r.get("category") or "").strip()
        opt_job_id = str(r.get("optimized_query_id") or "").strip()

        if not raw_job_id or not opt_sql:
            print(f"[WARN] row {i}: missing raw_query_id/optimized_query → skip")
            continue

        # 1) fetch plan from job
        props = None
        try:
            props = fetch_job_properties(client, raw_job_id)
        except Exception as e:
            print(f"[INFO] row {i}: failed to fetch job ({raw_job_id}) → fallback to EXPLAIN: {e}")
            if not raw_sql_sheet:
                print(f"[WARN] row {i}: raw_query is empty; fallback not possible → skip")
                continue
            try:
                props = fetch_plan_via_explain(client, raw_sql_sheet)
            except Exception as e2:
                print(f"[WARN] row {i}: failed to obtain EXPLAIN → skip ({e2})")
                continue

        # raw SQL (prefer sheet value; otherwise from job)
        raw_sql = raw_sql_sheet or extract_sql_from_props(props)

        # Optionally dump plan
        if args.plans_dir:
            dump_path = os.path.join(args.plans_dir, f"plan_row{i}_{raw_job_id}.json")
            with open(dump_path, "w", encoding="utf-8") as f:
                json.dump(props, f, ensure_ascii=False, indent=2)

        # Features → scale → L2
        q_vec = build_features_v2(props, raw_sql, schema_keys)
        q_scaled = scaler.transform(q_vec)
        q_unit = l2_normalize(q_scaled)
        vecs.append(q_unit.astype(np.float32))

        # Metadata row (raw only; optimized is stored as a paired reference)
        pair_id = str(uuid.uuid4())
        new_meta_rows.append({
            "id": f"{args.project}:{raw_job_id}",
            "pair_id": pair_id,
            "variant": "raw",
            "raw_job_id": raw_job_id,
            "opt_job_id": opt_job_id,
            "raw_sql_text": raw_sql,
            "opt_sql_text": opt_sql,
            "category": category
        })
        # Also store an optimized row for reference (not used for search)
        new_meta_rows.append({
            "id": f"{args.project}:{raw_job_id}:opt",
            "pair_id": pair_id,
            "variant": "optimized",
            "raw_job_id": raw_job_id,
            "opt_job_id": opt_job_id,
            "raw_sql_text": raw_sql,
            "opt_sql_text": opt_sql,
            "category": category
        })

    if not vecs:
        raise SystemExit("[ERROR] No records to register. Please check raw_query_id and optimized_query columns, as well as project/location.")

    X = np.vstack(vecs)  # only raw vectors are added to the index (optimized rows are metadata only)
    index.add(X)

    # Save
    faiss.write_index(index, os.path.join(args.artifacts_dir, FAISS_INDEX_NAME))

    meta_out = pd.concat([meta_df_existing, pd.DataFrame(new_meta_rows)], ignore_index=True)
    append_metadata(os.path.join(args.artifacts_dir, METADATA_PARQUET), meta_out.iloc[len(meta_df_existing):])

    print(f"[OK] Added {X.shape[0]} vectors.")
    print(f"[OK] Index -> {os.path.join(args.artifacts_dir, FAISS_INDEX_NAME)}")
    print(f"[OK] Metadata appended -> {os.path.join(args.artifacts_dir, METADATA_PARQUET)}")

if __name__ == "__main__":
    main()
