#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_rewrite_batch.py
Batch runner for query_rewrite_v3_faiss_temp0.py

- Reads a small inline mapping (or --mapping_json) from query_id to orig.sql path.
- For each query:
  * create a temp plan JSON from orig.sql
  * run ZERO and RAG modes
  * parse the JSON output and write {zero,rag}.sql next to orig.sql

Usage:
  python3 run_rewrite_batch.py --rewrite_script /abs/path/query_rewrite_v3_faiss_temp0.py \
      --artifacts_dir /abs/path/artifacts \
      --mapping_json /abs/path/mapping.json \
      [--model gpt-4o-mini] [--topk 5] [--min_similarity 0.10] [--debug]

The mapping.json format:
{
  "q3": "/path/to/queries_example/q3/orig.sql",
  "q6": "/path/to/queries_example/q6/orig.sql",
  "q14": "/path/to/queries_example/q14/orig.sql",
  "q9": "/path/to/queries_example/q9/orig.sql",
  "q21": "/path/to/queries_example/q21/orig.sql"
}
"""
import argparse, json, os, subprocess, sys, tempfile

def read_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def run_sql2plan(sql_path: str, out_json: str):
    # sql2planjson.py は同ディレクトリや絶対パスに置いてください
    helper = "sql2planjson.py"
    if not os.path.isabs(helper):
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql2planjson.py")
    cmd = [sys.executable, helper, "--sql", sql_path, "--out", out_json]
    subprocess.check_call(cmd)

def call_rewrite(script: str, plan_json: str, artifacts_dir: str, mode: str,
                 model: str, topk: int, min_similarity: float, debug: bool):
    cmd = [sys.executable, script,
           "--plan_path", plan_json,
           "--artifacts_dir", artifacts_dir,
           "--mode", mode,
           "--model", model,
           "--topk", str(topk),
           "--min_similarity", str(min_similarity)]
    if debug:
        cmd.append("--debug")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"rewrite failed (mode={mode})")
    out = proc.stdout.strip()
    try:
        m = out.find("{")
        n = out.rfind("}")
        if m >= 0 and n >= 0:
            out = out[m:n+1]
        data = json.loads(out)
    except Exception:
        print(out)
        raise
    opt_sql = (data.get("optimized_sql") or "").strip()
    rationale = (data.get("rationale") or "").strip()
    return opt_sql, rationale

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rewrite_script", required=True, help="Path to query_rewrite_v3_faiss_temp0.py")
    ap.add_argument("--artifacts_dir", required=True, help="Artifacts dir (FAISS index, scaler, metadata, feature schema)")
    ap.add_argument("--mapping_json", required=True, help="Path to mapping json")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--min_similarity", type=float, default=0.10)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    m = read_json(args.mapping_json)

    for qid, sql_path in m.items():
        sql_path = os.path.abspath(os.path.expanduser(sql_path))
        out_dir = os.path.dirname(sql_path)
        zero_path = os.path.join(out_dir, "zero.sql")
        rag_path  = os.path.join(out_dir, "rag.sql")
        rationale_txt = os.path.join(out_dir, "rewrite_rationale.txt")

        print(f"== {qid} ==")
        with tempfile.TemporaryDirectory() as td:
            plan_json = os.path.join(td, "plan.json")
            run_sql2plan(sql_path, plan_json)

            # ZERO
            zero_sql, zero_rat = call_rewrite(
                script=args.rewrite_script,
                plan_json=plan_json,
                artifacts_dir=args.artifacts_dir,
                mode="zero",
                model=args.model,
                topk=args.topk,
                min_similarity=args.min_similarity,
                debug=args.debug,
            )
            # RAG
            rag_sql, rag_rat = call_rewrite(
                script=args.rewrite_script,
                plan_json=plan_json,
                artifacts_dir=args.artifacts_dir,
                mode="rag",
                model=args.model,
                topk=args.topk,
                min_similarity=args.min_similarity,
                debug=args.debug,
            )

        if zero_sql:
            write_text(zero_path, zero_sql + "\n")
        else:
            print("[WARN] ZERO optimized_sql empty; keeping placeholder")
        if rag_sql:
            write_text(rag_path, rag_sql + "\n")
        else:
            print("[WARN] RAG optimized_sql empty; keeping placeholder")

        write_text(rationale_txt, f"[ZERO]\n{zero_rat}\n\n[RAG]\n{rag_rat}\n")
        print(f"Wrote: {zero_path}, {rag_path}, {rationale_txt}")

if __name__ == "__main__":
    main()
