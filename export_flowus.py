#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 FlowUs MCP 落盘的原始 page 数组导出扁平 JSON（build_calendar.py 的输入）。

关键坑（2026-10 实测）：
1. relation 字段是 {"id": "..."} 对象，不是裸 id —— 直接当 key 用会报 unhashable dict
2. 全表分页的 next_cursor 被 MCP 服务端截断（返回 'eyJvZm...NyJ9'），分页不可用。
   绕过：按 select 属性（考试地区）逐地区筛选拉取，每批 has_more=false。
3. 全表混有跨年记录（如 2025-07 的旧数据），必须按 start.year 过滤，不能只看地区

用法：
  python3 export_flowus.py --raw part0_all.json --out data/flowus_2026.json --year 2026
  # 多个 raw（按地区分别拉的）会自动合并去重
"""
import sys, os, json, argparse


def parse_dt(v):
    if not v:
        return None
    s = v.get("start") if isinstance(v, dict) else None
    return s or None


def load_pages(path):
    """兼容三种输入：{'结果':[...]} / {'<地区>':[...]} / [...]"""
    d = json.load(open(path, encoding="utf-8"))
    if isinstance(d, list):
        return d, None
    if "结果" in d:
        return d["结果"], d.get("has_more")
    # 地区字典（可能多地区）
    pages, hm = [], False
    for _, v in d.items():
        if isinstance(v, list):
            pages.extend(v)
        elif v is False:
            hm = True
    return pages, hm


def to_row(p):
    pr = p.get("properties", {})
    sel = (pr.get("考试地区") or {}).get("select")
    rel = (pr.get("父记录") or {}).get("relation") or []
    # relation 是 [{"id": "..."}]，取 id；空列表 → None
    parent = None
    if rel:
        first = rel[0]
        parent = first.get("id") if isinstance(first, dict) else first
    def t(v):
        return "".join(x.get("plain_text", "") for x in v) if v else ""
    return {
        "id": p["id"],
        "title": t((pr.get("公告") or {}).get("title")),
        "region": sel["name"] if sel else "",
        "parent": parent,
        "headcount": (pr.get("招聘人数") or {}).get("number"),
        "start": (pr.get("开始时间") or {}).get("date"),
        "end": (pr.get("结束时间") or {}).get("date"),
        "url": (pr.get("原文") or {}).get("url"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", nargs="+", required=True, help="MCP 落盘的原始 JSON（可多个）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--year", type=int, default=2026)
    args = ap.parse_args()

    by_id, incomplete = {}, []
    for path in args.raw:
        pages, hm = load_pages(path)
        if hm:
            incomplete.append(os.path.basename(path))
        for p in pages:
            if not isinstance(p, dict) or "properties" not in p:
                continue
            r = to_row(p)
            by_id[r["id"]] = r

    rows = list(by_id.values())
    # 年度过滤：以"开始时间"的年份为准；无日期的保留（主公告可能有创建日期）
    def yr(r):
        s = parse_dt(r.get("start"))
        return int(s[:4]) if s else None

    kept, dropped = [], []
    for r in rows:
        y = yr(r)
        (kept if (y is None or y == args.year) else dropped).append(r)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    json.dump(kept, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    mains = [r for r in kept if not r["parent"]]
    subs_with_date = [r for r in kept if r["parent"] and r["start"]]
    print(f"→ {args.out}")
    print(f"  合并去重后 {len(rows)} 行 → 保留 {len(kept)} 行（{args.year}年），丢弃跨年 {len(dropped)} 行")
    print(f"  主公告 {len(mains)} 场，有日期环节 {len(subs_with_date)} 条")
    for m in mains:
        n = sum(1 for r in kept if r["parent"] == m["id"] and r["start"])
        print(f"    [{m['region'] or '—':6}] {m['title']:24} 招{m['headcount'] or '—':>4}  环节{n}")
    if incomplete:
        print(f"  ⚠️ 以下来源 has_more=true（数据可能不全）：{', '.join(incomplete)}")
    if dropped:
        from collections import Counter
        print(f"  丢弃的跨年记录年份分布: {dict(Counter(yr(r) for r in dropped))}")


if __name__ == "__main__":
    main()