#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sql2planjson.py
Wrap a raw SQL string/file into a minimal BigQuery-like job JSON so that
query_rewrite_v3_faiss_temp0.py can read the SQL via --plan_path.

Usage:
  python3 sql2planjson.py --sql /path/to/input.sql --out /path/to/plan.json
"""
import argparse, json, sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sql", required=True, help="Path to input .sql file")
    ap.add_argument("--out", required=True, help="Path to output plan .json")
    args = ap.parse_args()

    try:
        with open(args.sql, "r", encoding="utf-8") as f:
            sql = f.read().strip()
    except Exception as e:
        print(f"[ERROR] failed to read SQL: {e}", file=sys.stderr)
        sys.exit(2)

    obj = {
        "statistics": {
            "query": {
                "query": sql
            }
        }
    }
    try:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] failed to write JSON: {e}", file=sys.stderr)
        sys.exit(2)

    print(f"Wrote {args.out}")

if __name__ == "__main__":
    main()
