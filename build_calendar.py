#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宁波事业编考试日历 — 统一生成器 v2

数据源（优先级从高到低）：
  1. FlowUs 2026 归档时间线（人工整理，含笔试出分/资格复审/面试，最全）
     文件：data/flowus_2026.json
  2. 监控抓取器解析结果（覆盖广但会漏站、会因反爬失败）
     由 exam_ics_generator.py 的 build_events() 产出

去重规则：同一 (地区, 环节) 且日期相差 ≤1 天的，视为同一事件，保留 FlowUs 版本。
输出：ningbo-exam.ics（单张全市日历）

用法：
  python3 build_calendar.py --out ../ningbo-exam.ics --year 2026
  python3 build_calendar.py --out ../ningbo-exam.ics --flowus-only   # 不跑抓取，快
"""

import sys, os, re, json, hashlib, argparse
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 监控项目脚本目录（抓取器+提取器在那儿）
MONITOR_SCRIPTS = os.environ.get(
    "NBO_MONITOR_SCRIPTS",
    os.path.expanduser("~/.hermes/projects/1-ningbo-exam-monitor/scripts"),
)
if os.path.isdir(MONITOR_SCRIPTS):
    sys.path.insert(0, MONITOR_SCRIPTS)

CST = timezone(timedelta(hours=8))
FLOWUS_JSON = os.path.join(HERE, "data", "flowus_2026.json")

# 环节名归一（FlowUs 用的说法不一：资格初审/资格初审时间/资格审核时间…）
STAGE_MAP = {
    # 抓取器用 "报名开始"，FlowUs 用 "报名时间"/"报名" —— 必须归一到同一个"报名"
    "报名时间": "报名", "报名": "报名", "报名开始": "报名", "现场报名": "现场报名",
    "资格初审": "资格初审", "资格初审时间": "资格初审", "资格审核时间": "资格初审",
    "查询并再次报名": "再次报名", "再次报名": "再次报名",
    "缴费确认时间": "缴费确认", "缴费确认": "缴费确认", "缴费": "缴费确认",
    "准考证打印": "准考证", "准考证": "准考证",
    "笔试": "笔试",
    "笔试出分": "笔试出分", "成绩公布": "笔试出分",
    "资格复审": "资格复审", "资格审核（面谈）": "资格复审", "资格确认": "资格复审",
    "面试": "面试", "面谈": "面试", "第一轮面试（面谈）": "面试", "首轮面试（面谈）": "面试",
    # 象山人才引进有两轮面试，必须分开——归一成"面试"会互相吞掉
    "第二轮面试": "第二轮面试",
}

# 提醒提前天数
ALARM = {"报名": 1, "现场报名": 1, "资格初审": 1, "再次报名": 1, "缴费确认": 1,
         "准考证": 3, "笔试": 7, "笔试出分": 0, "资格复审": 3, "面试": 3,
         "第二轮面试": 3}


def norm_stage(raw: str) -> str:
    return STAGE_MAP.get(raw.strip(), raw.strip())


def fold(line: str) -> str:
    """RFC5545 折行：每行 ≤75 字节（续行首字符带前导空格，占 1 字节）。"""
    if len(line.encode("utf-8")) <= 75:
        return line
    segs, cur, cur_bytes = [], [], 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        limit = 75 if not segs else 74
        if cur and cur_bytes + n > limit:
            segs.append("".join(cur))
            cur, cur_bytes = [], 0
        cur.append(ch)
        cur_bytes += n
    if cur:
        segs.append("".join(cur))
    return "\r\n ".join(segs)


def ics_escape(t: str) -> str:
    if not t:
        return ""
    t = str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return t.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


# ---------- FlowUs 源 ----------

def parse_flowus_dt(v):
    if not v:
        return None
    s = v.get("start") if isinstance(v, dict) else None
    if not s:
        return None
    for fmt in ("%Y/%m/%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=CST)
        except ValueError:
            continue
    return None


def events_from_flowus(year: int):
    if not os.path.exists(FLOWUS_JSON):
        print(f"[warn] FlowUs 数据不存在: {FLOWUS_JSON}", file=sys.stderr)
        return []
    rows = json.load(open(FLOWUS_JSON, encoding="utf-8"))
    mains = {r["id"]: r for r in rows if not r.get("parent")}
    events = []
    for r in rows:
        if not r.get("parent"):
            continue
        main = mains.get(r["parent"])
        if not main:
            continue
        st = parse_flowus_dt(r.get("start"))
        if not st or st.year != year:
            continue
        en = parse_flowus_dt(r.get("end"))
        stage = norm_stage(r.get("title", ""))
        if not en:
            en = st + timedelta(hours=2 if stage == "笔试" else 1)
        region = main.get("region") or r.get("region") or ""
        if not region:
            continue
        desc = [f"环节：{r['title']}", f"招录人数：{main.get('headcount') or '—'}"]
        if main.get("url"):
            desc.append(f"公告原文：{main['url']}")
        desc.append("来源：FlowUs 2026 归档（人工整理）")
        desc.append("⚠️ 以官方公告原文为准。")
        events.append({
            # UID 必须用原始环节名：归一后「首轮面试」和「面试」同名，
            # 用归一名会让同场次内两个不同环节生成相同 UID（订阅端会互相覆盖）
            "uid_src": f"flowus|{main['id']}|{r['title'].strip()}",
            "title": f"【{region}】{stage}｜{main['title']}",
            "start": st, "end": en, "all_day": False,
            "desc": "\n".join(desc),
            "alarm": ALARM.get(stage, 1),
            "region": region, "stage": stage,
            "main_id": main["id"], "main_title": main["title"],
            "src": "flowus",
            "url": main.get("url") or "",
        })
    return events


# ---------- 抓取器源（可选） ----------

def events_from_scraper(year: int, days: int):
    try:
        import exam_ics_generator as G
    except Exception as e:
        print(f"[warn] 抓取器不可用，跳过: {e}", file=sys.stderr)
        return []
    try:
        raw, stats = G.build_events(days=days, workers=8, max_per_source=25)
    except Exception as e:
        print(f"[warn] 抓取器运行失败，跳过: {e}", file=sys.stderr)
        return []
    out = []
    for ev in raw:
        if ev["start"].year != year:
            continue
        st_norm = STAGE_MAP.get(ev["stage"], ev["stage"])
        # 标题里的环节名同步换成归一名，避免同一日历里"报名"和"报名开始"混排
        title = re.sub(rf"^【[^】]+】{re.escape(ev['stage'])}｜",
                       lambda m: m.group(0).replace(ev["stage"], st_norm),
                       ev["title"])
        out.append({
            "uid_src": f"scraper|{ev['region']}|{ev['full_title']}|{ev['stage']}",
            "title": title,
            "start": ev["start"], "end": ev["end"], "all_day": ev["all_day"],
            "desc": ev["desc"], "alarm": ev["alarm"],
            "region": ev["region"], "stage": st_norm, "src": "scraper",
            # 抓取器无场次ID，用完整标题占位（跨源匹配靠 merge 的 36h + 同名兜底，见 dedup_cross_source）
            "main_id": ev.get("full_title", ""), "main_title": ev.get("full_title", ""),
            "url": ev.get("url", ""),
        })
    return out


# ---------- 合并去重 ----------

def merge(events):
    """去重。

    关键：FlowUs 是人工整理的结构化数据，同场次同名的记录就是两个不同环节
    （如"首轮面试 5-16"和"面试 5-17"是分开的两场），**同源不做时间窗合并**，
    只有跨源（flowus vs 抓取器）才用 36h 窗口判重。

    键必须含"场次"，不能只用 (地区, 环节)：
    同一地区同年有多场考试（如镇海区 510招28人笔试5-10 / 人才引进招22人笔试4-08），
    报名、再次报名、缴费环节日期完全重合，只按 (地区,环节) 会整场吞掉。
    """
    def key(e):
        return (e["region"], e.get("main_id") or e["main_title"], e["stage"])

    events = sorted(events, key=lambda e: (e["start"], e["src"]))
    merged = []
    flowus_idx = {}   # key → 该场次已收录的 flowus 环节数（用于跨源判重）
    for e in events:
        k = key(e)
        if e["src"] == "flowus":
            # 同源：同名直接都保留（不同环节可能同名同月）
            merged.append(e)
            flowus_idx.setdefault(k, 0)
            flowus_idx[k] += 1
        else:
            # 跨源判重：只按 (地区, 环节) + 36h 窗口，不看 main_id
            # 原因：FlowUs 的场次ID是 UUID，抓取器没有ID（用完整标题），
            #         两者无法直接比对；场次差异由时间窗口自然区分
            #         （镇海两场考试报名日相同、笔试相差一月，窗口不会误判）
            dup = any(m["src"] == "flowus" and m["region"] == e["region"]
                      and m["stage"] == e["stage"]
                      and abs((m["start"] - e["start"]).total_seconds()) <= 36 * 3600
                      for m in merged)
            if not dup:
                merged.append(e)
    return merged


# ---------- 渲染 ----------

def render(events, out_path, state_path, title="宁波事业编考试日历"):
    now = datetime.now(CST)
    old = {}
    if os.path.exists(state_path):
        try:
            old = json.load(open(state_path, encoding="utf-8"))
        except Exception:
            old = {}

    new_state = {}
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Ningbo Exam Monitor//宁波事业编考试日历//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        fold(f"X-WR-CALNAME:{title}"),
        fold("X-WR-CALDESC:" + ics_escape("宁波各区县事业单位公开招聘/选聘考试时间节点（自动生成，以官方公告为准）")),
        "X-WR-TIMEZONE:Asia/Shanghai",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]

    for ev in sorted(events, key=lambda e: e["start"]):
        uid = hashlib.sha1(ev["uid_src"].encode("utf-8")).hexdigest() + "@ningbo-exam-cal"
        fp = hashlib.sha1(f"{ev['start']}|{ev['end']}|{ev['desc']}".encode()).hexdigest()
        prev = old.get(uid)
        seq = prev.get("seq", 0) if prev and prev.get("fp") == fp else ((prev.get("seq", 0) + 1) if prev else 1)
        new_state[uid] = {"fp": fp, "seq": seq, "stage": ev["stage"],
                          "region": ev["region"], "start": fmt_dt(ev["start"])}

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f"DTSTAMP:{fmt_dt(now)}")
        if ev["all_day"]:
            lines.append(f"DTSTART;VALUE=DATE:{ev['start'].strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{(ev['end'] + timedelta(days=1)).strftime('%Y%m%d')}")
        else:
            lines.append(f"DTSTART;TZID=Asia/Shanghai:{fmt_dt(ev['start'])}")
            lines.append(f"DTEND;TZID=Asia/Shanghai:{fmt_dt(ev['end'])}")
        lines.append(fold(f"SUMMARY:{ics_escape(ev['title'])}"))
        lines.append(fold(f"DESCRIPTION:{ics_escape(ev['desc'])}"))
        if ev.get("url"):
            lines.append(fold(f"URL:{ics_escape(ev['url'])}"))
        lines.append(f"SEQUENCE:{seq}")
        lines.append(f"CATEGORIES:{ics_escape(ev['region'])}")
        if ev.get("alarm"):
            lines.append("BEGIN:VALARM")
            lines.append("ACTION:DISPLAY")
            lines.append(fold(f"DESCRIPTION:{ics_escape(ev['title'])}"))
            lines.append(f"TRIGGER:-P{ev['alarm']}D" if ev["alarm"] else "TRIGGER:PT0M")
            lines.append("END:VALARM")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    content = "\r\n".join(lines) + "\r\n"

    prev_content = open(out_path, encoding="utf-8").read() if os.path.exists(out_path) else ""
    changed = content != prev_content
    if changed or not os.path.exists(out_path):
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    json.dump(new_state, open(state_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return content, changed


def validate(content: str):
    """返回问题列表，空=通过"""
    problems = []
    raw = content.encode("utf-8")
    lines = raw.split(b"\r\n")
    over = [l for l in lines if len(l) > 75]
    if over:
        problems.append(f"{len(over)} 行超过 75 字节")
    if raw.count(b"\n") != raw.count(b"\r\n"):
        problems.append("存在非 CRLF 换行")
    for tag in ("VCALENDAR", "VEVENT", "VALARM"):
        b = raw.count(f"BEGIN:{tag}".encode())
        e = raw.count(f"END:{tag}".encode())
        if b != e:
            problems.append(f"{tag} 开闭不配对 ({b}/{e})")
    uids = [l.split(b":")[1] for l in lines if l.startswith(b"UID:")]
    if len(uids) != len(set(uids)):
        problems.append("UID 重复")
    if not raw.endswith(b"END:VCALENDAR\r\n"):
        problems.append("结尾缺少 END:VCALENDAR")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--days", type=int, default=400, help="抓取器时间窗")
    ap.add_argument("--flowus-only", action="store_true", help="只用 FlowUs，不跑抓取")
    ap.add_argument("--state", default=None)
    args = ap.parse_args()

    print(f"[1/3] 载入 FlowUs {args.year} 时间线...", flush=True)
    evs = events_from_flowus(args.year)
    n_flowus = len(evs)
    print(f"      FlowUs 事件: {n_flowus}")

    n_scraper = 0
    if not args.flowus_only:
        print("[2/3] 跑监控抓取器（补漏）...", flush=True)
        evs += events_from_scraper(args.year, args.days)
        n_scraper = len(evs) - n_flowus
        print(f"      抓取器事件: {n_scraper}")

    merged = merge(evs)
    print(f"[3/3] 合并去重: {n_flowus}+{n_scraper} → {len(merged)}")

    state = args.state or os.path.join(HERE, "data", "ics_state.json")
    content, changed = render(merged, args.out, state)

    problems = validate(content)
    status = "✅ 校验通过" if not problems else "❌ " + "; ".join(problems)
    print(f"\n{args.out}: {len(content)} 字节, {content.count('BEGIN:VEVENT')} 事件, "
          f"{'已更新' if changed else '无变化'} → {status}")

    from collections import Counter
    print("\n按地区:")
    for reg, n in Counter(e["region"] for e in merged).most_common():
        print(f"  {reg:8} {n:3} 事件")
    print("\n按环节:")
    for st, n in Counter(e["stage"] for e in merged).most_common():
        print(f"  {st:8} {n:3}")
    if problems:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())