#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
query_rewrite_v3_faiss_temp0.py
--------------------------------
Fix the default LLM temperature at **0.0** (deterministic).
You can override it with --temperature if needed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import pandas as pd
except Exception:
    pd = None  # type: ignore

try:
    import faiss  # type: ignore
except Exception:
    faiss = None  # type: ignore

try:
    import joblib  # type: ignore
except Exception:
    joblib = None  # type: ignore


# ========= Artifacts / Filenames =========
FAISS_INDEX_NAME = "faiss_v2_cosine.index"
SCALER_NAME = "scaler_v2.pkl"
METADATA_PARQUET = "metadata_v2.parquet"
METADATA_CSV = "metadata_v2.csv"
METADATA_CSV_PREVIEW = "metadata_v2_preview.csv"
FEATURE_SCHEMA_NAME = "feature_schema_v2.json"


@dataclass
class Neighbor:
    raw_sql: str
    optimized_sql: str
    features: Dict[str, Any] = field(default_factory=dict)
    notes: Optional[str] = None
    id: Optional[str] = None


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def extract_sql_from_plan_json(plan_path: str, debug: bool=False) -> Optional[str]:
    obj = _read_json(plan_path)
    if obj is None:
        print(f"[ERROR] failed to read plan JSON: {plan_path}", file=sys.stderr)
        return None

    candidates = [
        ("configuration", "query", "query"),
        ("statistics", "query", "query"),
        ("job", "configuration", "query", "query"),
        ("query",),
    ]
    for path in candidates:
        cur = obj
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok and isinstance(cur, str) and cur.strip():
            if debug:
                print(f"[DEBUG] SQL extracted via path {path}", file=sys.stderr)
            return cur.strip()

    for k in ["originalQuery", "text", "sql"]:
        v = obj.get(k) if isinstance(obj, dict) else None
        if isinstance(v, str) and v.strip():
            if debug:
                print(f"[DEBUG] SQL extracted via key '{k}'", file=sys.stderr)
            return v.strip()

    if debug:
        print("[DEBUG] SQL not found in plan JSON", file=sys.stderr)
    return None


def load_feature_keys(artifacts_dir: str) -> List[str]:
    p = os.path.join(artifacts_dir, FEATURE_SCHEMA_NAME)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("keys") or data.get("feature_keys") or data["keys"]


def l2_normalize(a: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(a, axis=1, keepdims=True) + 1e-12
    return a / n


def safe_get(d: Dict[str, Any], path: List[str], default=0):
    cur = d
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


# ========= v2 features =========
def summarize_plan_for_features(plan_json: Dict[str, Any]) -> Dict[str, Any]:
    q = plan_json.get("statistics", {}).get("query", {}) or {}
    stages = q.get("queryPlan", []) or plan_json.get("query_plan", []) or []
    n_stages = len(stages)

    total_slot_ms_top = float(q.get("totalSlotMs", plan_json.get("total_slot_ms", 0)) or 0)
    total_bytes_proc  = float(q.get("totalBytesProcessed", plan_json.get("total_bytes_processed", 0)) or 0)

    total_slot_ms = 0.0
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
        total_slot_ms += sm
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

    if not stage_slot_ms and total_slot_ms_top > 0:
        total_slot_ms = total_slot_ms_top
        stage_slot_ms = [total_slot_ms_top]
    if bytes_read == 0 and total_bytes_proc > 0:
        bytes_read = total_bytes_proc

    avg_slot_ms = float(np.mean(stage_slot_ms)) if stage_slot_ms else 0.0
    p95_slot_ms = float(np.percentile(stage_slot_ms, 95)) if stage_slot_ms else 0.0

    return {
        "n_stages": float(n_stages),
        "n_joins": float(n_joins),
        "n_sorts": float(n_sorts),
        "n_aggregations": float(n_aggs),
        "total_slot_ms": float(total_slot_ms if total_slot_ms > 0 else total_slot_ms_top),
        "avg_slot_ms": float(avg_slot_ms),
        "p95_slot_ms": float(p95_slot_ms),
        "bytes_read_total": float(bytes_read if bytes_read > 0 else total_bytes_proc),
        "bytes_written_total": float(bytes_written),
        "records_read_total": float(rec_read),
        "records_written_total": float(rec_written),
    }


def basic_sql_stats(raw_sql: str) -> Dict[str, Any]:
    s = (raw_sql or "").lower()
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


def build_features_v2(plan_json: Dict[str, Any], raw_sql: str) -> Tuple[Dict[str, float], List[str]]:
    pj = summarize_plan_for_features(plan_json)
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
    return feat_map, list(feat_map.keys())


def load_metadata_df(artifacts_dir: str):
    if pd is None:
        raise RuntimeError("pandas is required to read metadata files.")
    pq = os.path.join(artifacts_dir, METADATA_PARQUET)
    csv = os.path.join(artifacts_dir, METADATA_CSV)
    csv_prev = os.path.join(artifacts_dir, METADATA_CSV_PREVIEW)
    if os.path.exists(pq):
        return pd.read_parquet(pq)
    if os.path.exists(csv):
        return pd.read_csv(csv)
    if os.path.exists(csv_prev):
        return pd.read_csv(csv_prev)
    raise FileNotFoundError(f"No metadata file found under: {artifacts_dir}")


def retrieve_neighbors_with_faiss(
    artifacts_dir: str,
    plan_json: Dict[str, Any],
    raw_sql: str,
    topk: int,
    min_similarity: float,
    debug: bool=False,
):
    if faiss is None or joblib is None or pd is None:
        raise RuntimeError("faiss/joblib/pandas are required for neighbor retrieval.")
    index_path = os.path.join(artifacts_dir, FAISS_INDEX_NAME)
    scaler_path = os.path.join(artifacts_dir, SCALER_NAME)
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"FAISS index not found: {index_path}")
    if not os.path.exists(scaler_path):
        raise FileNotFoundError(f"Scaler not found: {scaler_path}")
    index = faiss.read_index(index_path)
    scaler = joblib.load(scaler_path)
    meta = load_metadata_df(artifacts_dir)

    feature_keys = load_feature_keys(artifacts_dir)

    feat_map, _ = build_features_v2(plan_json, raw_sql)
    missing = [k for k in feature_keys if k not in feat_map]
    if missing:
        raise SystemExit(f"feature mismatch against schema: missing={missing}")
    q_vec = np.array([[float(feat_map[k]) for k in feature_keys]], dtype=np.float32)
    q_scaled = scaler.transform(q_vec)
    q_unit = l2_normalize(q_scaled).astype(np.float32)
    if debug:
        print("[DEBUG] q_unit norm:", float(np.linalg.norm(q_unit)))
        print("[DEBUG] index.ntotal:", index.ntotal)

    D, I = index.search(q_unit, topk)

    meta_raw = meta[meta["variant"].astype(str).str.lower()=="raw"].reset_index(drop=True)
    meta_opt = meta[meta["variant"].astype(str).str.lower()=="optimized"].reset_index(drop=True)

    neighbors = []
    seen_pairs = set()

    for sim, idx in zip(D[0], I[0]):
        if idx < 0 or idx >= len(meta_raw):
            continue
        if sim < min_similarity:
            continue
        rec = meta_raw.iloc[int(idx)].to_dict()

        pid = rec.get("pair_id") or rec.get("pair") or rec.get("group_id")
        if not pid or pid in seen_pairs:
            continue

        row = meta_opt[meta_opt["pair_id"] == pid].head(1)
        if row.empty:
            continue

        raw_sql_text = (
            rec.get("raw_sql_text") or rec.get("sql_text") or rec.get("raw_sql") or rec.get("sql") or ""
        )
        opt_sql_text = (
            row.iloc[0].get("opt_sql_text") or row.iloc[0].get("optimized_sql") or ""
        )
        if not raw_sql_text or not opt_sql_text:
            continue

        f = {
            "similarity": float(sim),
            "n_joins": rec.get("n_joins") or rec.get("sql_joins_count") or 0,
            "num_predicates": rec.get("where_predicates_count") or rec.get("num_predicates") or 0,
            "estimated_bytes": rec.get("bytes_read_total") or rec.get("estimated_bytes") or 0,
        }

        neighbors.append({
            "raw_sql": raw_sql_text,
            "optimized_sql": opt_sql_text,
            "features": f,
            "notes": str(rec.get("notes") or ""),
            "id": str(rec.get("id") or ""),
        })
        seen_pairs.add(pid)

    if debug:
        print("[DEBUG] retrieved neighbors:", len(neighbors))

    return neighbors


# ===== Prompt construction =====

PROMPT_HEADER = """You are a seasoned reviewer of SQL performance optimization.
In this task, strictly follow the principle of "applying reference examples" and **transpose** the transformation patterns from the given reference examples (raw→optimized) onto the input SQL.
Do not invent freely or speculate; only perform transformations that structurally correspond to the reference examples."""

PROMPT_RULES = """
[Strict Rules]
1) Semantic preservation: Do not change the original query's meaning, result set, or aggregation granularity.
2) Transcribe from reference: Only apply transformations that **match** what the reference examples actually did.
3) Allow limited generalization: Even if columns or types differ, you may apply a pattern when the **logical structure is the same**.
   Examples: (a) range using OR → normalize to (NOT) BETWEEN,
             (b) equivalent expansion of aggregate functions (AVG(x) ≒ SAFE_DIVIDE(SUM(x), COUNT(x))),
             (c) reuse SELECT aliases in ORDER BY to avoid recomputation.
4) Prohibited: introducing objects not in the schema; adding/removing JOINs; changing grouping keys; introducing new functions/hints; cosmetic LIMIT;
               meaningless subqueries or unnecessary nesting (cosmetic-only changes).
5) Formatting: BigQuery Standard SQL. Use aliases and indentation.
6) Output format: return **only** the following JSON.
   {
     "optimized_sql": "...",
     "rationale": "Which transformation(s) from which reference(s) were applied where. If none matched, state that explicitly."
   }
7) Application policy: Apply changes **only when** the above patterns are applicable. If none match, **make no changes** (do not force changes).
"""

def make_pattern_hints(input_sql: str) -> str:
    hints = []
    s = input_sql.lower()

    m = re.search(r"(\b[a-z_][a-z0-9_]*\b)\s*<\s*([0-9.]+)\s*or\s*\1\s*>\s*([0-9.]+)", s)
    if m:
        col, a, b = m.group(1), m.group(2), m.group(3)
        hints.append(f"- Detected: {col} < {a} OR {col} > {b} → could normalize to {col} NOT BETWEEN {a} AND {b}")

    if "order by" in s and "sum(" in s:
        alias_m = re.findall(r"sum\s*\(\s*([a-z0-9_\.]+)\s*\)\s+as\s+([a-z0-9_]+)", s)
        order_m = re.findall(r"order\s+by\s+sum\s*\(\s*([a-z0-9_\.]+)\s*\)\s*(asc|desc)?", s)
        if alias_m and order_m:
            sum_cols_in_select = {c for (c, a) in alias_m}
            for (c, _dir) in order_m:
                if c in sum_cols_in_select:
                    hints.append("- Detected: ORDER BY aggregate expression can reuse the SELECT alias (avoid recomputation)")
                    break

    return "\n".join(hints) if hints else ""


def build_prompt(input_sql: str, ref_neighbors: List[Dict[str, Any]], mode: str) -> str:
    mode_note = "(zero-shot: no references)" if mode == "zero" else "(RAG: with references)"

    examples_block = []
    for i, nb in enumerate(ref_neighbors, 1):
        f = nb.get("features", {}) or {}
        features_str = ", ".join(f"{k}={v}" for k, v in f.items()) if f else "n/a"
        note = f"\n# notes: {nb.get('notes')}" if nb.get("notes") else ""
        examples_block.append(
            f"""### Reference {i}
# features: {features_str}{note}
# raw:
{nb.get('raw_sql','')}

# optimized:
{nb.get('optimized_sql','')}
"""
        )
    examples_text = "\n".join(examples_block)
    ref_section = f"\n[References (raw → optimized)]\n{examples_text}\n" if ref_neighbors else "\n[References] (none)\n"

    hints = make_pattern_hints(input_sql)
    hint_block = f"\n[Candidate hints for the input]\n{hints}\n" if hints else ""

    prompt = f"""{PROMPT_HEADER} {mode_note}

{PROMPT_RULES}
{hint_block}{ref_section}
[Input SQL]
{input_sql}

[Task]
- Optimize **only** within the scope where the reference patterns match and the structure is logically isomorphic.
- Do **not** perform transformations that do not exist in the reference examples.
- Return JSON **only**.
"""
    return prompt


def call_llm(prompt: str, model: str = "gpt-4o-mini", temperature: float = 0.0, max_tokens: int = 1200) -> str:
    try:
        import openai  # type: ignore
    except Exception:
        print("[WARN] openai package not found. Use --dry-run to inspect the prompt.", file=sys.stderr)
        return ""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[WARN] OPENAI_API_KEY is not set. Use --dry-run to inspect the prompt.", file=sys.stderr)
        return ""
    openai.api_key = api_key
    try:
        resp = openai.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a meticulous SQL optimization assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}", file=sys.stderr)
        return ""


# ===== Post-guards (fire only when applicable) =====
def normalize_or_to_not_between(sql: str):
    def repl(m: re.Match) -> str:
        col, a, b = m.group(1), m.group(2), m.group(3)
        return f"{col} NOT BETWEEN {a} AND {b}"
    before = sql
    after = re.sub(r"(\b[a-z_][a-z0-9_]*\b)\s*<\s*([0-9.]+)\s*OR\s*\1\s*>\s*([0-9.]+)", repl, sql, flags=re.I)
    return after, (before != after)


def rewrite_orderby_sum_to_alias(sql: str):
    s_low = sql.lower()
    alias_pairs = re.findall(r"sum\s*\(\s*([a-z0-9_\.]+)\s*\)\s+as\s+([a-z0-9_]+)", s_low)
    order_by = re.findall(r"order\s+by\s+sum\s*\(\s*([a-z0-9_\.]+)\s*\)\s*(asc|desc)?", s_low)
    if not alias_pairs or not order_by:
        return sql, False
    alias_map = {col: alias for (col, alias) in alias_pairs}
    changed = False
    new_sql = sql
    for (col, direction) in order_by:
        if col in alias_map:
            alias = alias_map[col]
            pattern = re.compile(rf"ORDER\s+BY\s+SUM\s*\(\s*{re.escape(col)}\s*\)\s*(ASC|DESC)?", re.I)
            repl = f"ORDER BY {alias}" + (f" {direction.upper()}" if direction else "")
            new_sql, n = pattern.subn(repl, new_sql, count=1)
            if n > 0:
                changed = True
    return new_sql, changed


def apply_safe_fallbacks(input_sql: str, llm_json: Dict[str, Any]) -> Dict[str, Any]:
    opt = (llm_json.get("optimized_sql") or "").strip()
    rat = (llm_json.get("rationale") or "").strip()
    if not opt:
        opt = input_sql

    changed_any = False
    opt2, ch1 = normalize_or_to_not_between(opt)
    changed_any |= ch1
    opt3, ch2 = rewrite_orderby_sum_to_alias(opt2)
    changed_any |= ch2

    if changed_any:
        add = []
        if ch1:
            add.append("Normalized OR-range condition to NOT BETWEEN (equivalent)")
        if ch2:
            add.append("Reused SELECT alias in ORDER BY instead of aggregate recomputation")
        rat2 = (rat + " / " if rat else "") + "；".join(add)
        return {"optimized_sql": opt3, "rationale": rat2}

    if not rat:
        rat = "No applicable patterns found from references/generalization; left unchanged."
    return {"optimized_sql": opt, "rationale": rat}


# ===== Main =====
def main():
    parser = argparse.ArgumentParser(description="RAG or ZERO SQL rewrite (temperature default = 0.0)")
    parser.add_argument("--plan_path", type=str, required=True)
    parser.add_argument("--artifacts_dir", type=str, required=True)
    parser.add_argument("--mode", type=str, choices=["rag", "zero"], default="rag")
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument("--min_similarity", type=float, default=0.10)
    parser.add_argument("--model", type=str, default="gpt-4o-mini")
    parser.add_argument("--temperature", type=float, default=0.0)  # ★ default 0.0
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    input_sql = extract_sql_from_plan_json(args.plan_path, debug=args.debug)
    if not input_sql:
        print("[ERROR] could not extract input SQL from --plan_path.", file=sys.stderr)
        sys.exit(2)

    ranked = []
    if args.mode == "rag":
        plan_json = _read_json(args.plan_path) or {}
        try:
            neighbors_all = retrieve_neighbors_with_faiss(
                artifacts_dir=args.artifacts_dir,
                plan_json=plan_json,
                raw_sql=input_sql,
                topk=args.topk * 3,
                min_similarity=args.min_similarity,
                debug=args.debug,
            )
        except Exception as e:
            print(f"[ERROR] neighbor retrieval failed: {e}", file=sys.stderr)
            sys.exit(3)

        if not neighbors_all:
            if args.debug:
                print("[DEBUG] neighbors=0 → RAG selected but no references available; proceed as zero-shot.")
            ranked = []
        else:
            # prioritize n_joins == 0; tie-break by similarity (descending)
            def sort_key(nb):
                f = nb.get("features", {})
                return (f.get("n_joins", 99), -float(f.get("similarity", 0.0)))
            neighbors_all.sort(key=sort_key)
            ranked = neighbors_all[:args.topk]

            if args.debug:
                print("===== [DEBUG] Ranked reference neighbors =====")
                for i, nb in enumerate(ranked, 1):
                    print(f"[{i}] id={nb.get('id')} features={json.dumps(nb.get('features', {}), ensure_ascii=False)}")
    else:
        if args.debug:
            print("[DEBUG] ZERO mode: no references will be used.")

    prompt = build_prompt(input_sql=input_sql, ref_neighbors=ranked, mode=args.mode)

    if args.debug or args.dry_run:
        print("\n===== [DEBUG] Final Prompt =====\n")
        print(prompt)
        if args.dry_run:
            return

    llm_text = call_llm(prompt, model=args.model, temperature=args.temperature)
    if not llm_text:
        print("[ERROR] empty LLM response. Check API settings or use --dry-run to inspect the prompt.", file=sys.stderr)
        sys.exit(2)

    text = llm_text.strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)
    try:
        payload = json.loads(text)
    except Exception:
        print("[WARN] LLM response could not be parsed as JSON. Printing raw text below.\n")
        print(llm_text)
        sys.exit(0)

    payload2 = apply_safe_fallbacks(input_sql, payload)
    print(json.dumps(payload2, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
