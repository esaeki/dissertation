#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
summarize_bq_eval.py
- /tmp/bq_eval_results.csv（bq_cost_eval.py の出力）を読み込み
- クエリ単位で最速バリアント（orig/zero/rag）を判定
- 等価性・スロット削減量などのサマリを Markdown/CSV に出力
"""

import argparse
import csv
import math
from collections import defaultdict
from typing import Dict, Any, List, Optional


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_csv", required=True, help="Path to bq_eval_results.csv")
    ap.add_argument("--out_md", default="/tmp/bq_eval_summary.md", help="Output markdown path")
    ap.add_argument("--out_csv", default="/tmp/bq_eval_summary.csv", help="Output summary CSV path")
    return ap.parse_args()


def safe_int(x) -> Optional[int]:
    try:
        if x is None or x == "":
            return None
        v = int(x)
        return v
    except Exception:
        try:
            return int(float(x))
        except Exception:
            return None


def pick_best(variant_slots: Dict[str, Optional[int]]) -> Optional[str]:
    # variant_slots: {"orig": ms or None, "zero": ms or None, "rag": ms or None}
    best_variant = None
    best_val = math.inf
    for v in ["orig", "zero", "rag"]:
        ms = variant_slots.get(v)
        if isinstance(ms, int) and ms >= 0:
            if ms < best_val:
                best_val = ms
                best_variant = v
    return best_variant


def main():
    args = parse_args()

    # 読み込み
    rows: List[Dict[str, Any]] = []
    with open(args.in_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    # qid ごとに集約
    by_qid: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "qname": "",
        "equivalence": "",
        "slots": {"orig": None, "zero": None, "rag": None},
        "bytes": {"orig": None, "zero": None, "rag": None},
    })

    for r in rows:
        qid = r["qid"]
        qname = r.get("qname", qid)
        variant = r.get("variant", "")
        eq = r.get("equivalence_orig_vs_rag", "")

        slot_ms = safe_int(r.get("total_slot_ms"))
        bytes_proc = safe_int(r.get("total_bytes_processed"))

        by_qid[qid]["qname"] = qname
        # equivalence は orig/rag の比較なので、同一 qid 内で同じはず。最後に残ったものでOK
        by_qid[qid]["equivalence"] = eq or by_qid[qid]["equivalence"]
        if variant in ("orig", "zero", "rag"):
            by_qid[qid]["slots"][variant] = slot_ms
            by_qid[qid]["bytes"][variant] = bytes_proc

    # 要約レコードを生成
    summary_rows: List[Dict[str, Any]] = []
    for qid, rec in by_qid.items():
        qname = rec["qname"]
        eq = rec["equivalence"] or "UNKNOWN"
        slots = rec["slots"]

        best_variant = pick_best(slots)
        orig_slot = slots.get("orig")
        zero_slot = slots.get("zero")
        rag_slot = slots.get("rag")
        best_slot = slots.get(best_variant) if best_variant else None

        # 削減量（orig→best）
        slot_red_orig_best = None
        if isinstance(orig_slot, int) and isinstance(best_slot, int):
            slot_red_orig_best = orig_slot - best_slot

        # RAG vs ZERO
        rag_vs_zero = "NA"
        if isinstance(rag_slot, int) and isinstance(zero_slot, int):
            if rag_slot < zero_slot:
                rag_vs_zero = "RAG better"
            elif rag_slot > zero_slot:
                rag_vs_zero = "Zero better"
            else:
                rag_vs_zero = "Tie"

        summary_rows.append({
            "qid": qid,
            "qname": qname,
            "equivalence": eq,
            "best_variant": best_variant or "",
            "orig_slot_ms": orig_slot,
            "zero_slot_ms": zero_slot,
            "rag_slot_ms": rag_slot,
            "best_slot_ms": best_slot,
            "slot_reduction_orig_to_best": slot_red_orig_best,
            "rag_vs_zero": rag_vs_zero,
        })

    # Markdown 出力
    md_lines = []
    md_lines.append("| Query | Equivalence | Best Variant | Slot Reduction (orig→best) | orig ms | zero ms | rag ms | RAG vs ZERO |")
    md_lines.append("|------|-------------|--------------|-----------------------------:|--------:|--------:|-------:|-------------|")
    for r in summary_rows:
        md_lines.append(
            f"| {r['qname']} ({r['qid']}) | {r['equivalence']} | **{(r['best_variant'] or '').upper()}** | "
            f"{'' if r['slot_reduction_orig_to_best'] is None else str(r['slot_reduction_orig_to_best'])+' ms'} | "
            f"{'' if r['orig_slot_ms'] is None else r['orig_slot_ms']} | "
            f"{'' if r['zero_slot_ms'] is None else r['zero_slot_ms']} | "
            f"{'' if r['rag_slot_ms'] is None else r['rag_slot_ms']} | "
            f"{r['rag_vs_zero']} |"
        )

    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    # CSV 出力
    out_fields = [
        "qid",
        "qname",
        "equivalence",
        "best_variant",
        "orig_slot_ms",
        "zero_slot_ms",
        "rag_slot_ms",
        "best_slot_ms",
        "slot_reduction_orig_to_best",
        "rag_vs_zero",
    ]
    with open(args.out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields)
        w.writeheader()
        for r in summary_rows:
            w.writerow(r)

    print(f"Wrote summary markdown to {args.out_md}")
    print(f"Wrote summary csv to {args.out_csv}")


if __name__ == "__main__":
    main()
