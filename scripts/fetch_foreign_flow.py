#!/usr/bin/env python3
"""
fetch_foreign_flow.py — 외국인/기관 현물 순매수 합산 + 바실리 시그널
소스: data/kr/screener/investor_hist.json (fetch_screener.py가 생성)
출력: data/dashboard/foreign_flow.json

시그널 계산:
  - 5MA / 20MA (이동평균)
  - ±2σ 밴드 (20일 표준편차 기반)
  - 연속 매도/매수 일수
  - 매수/매도 시그널 (밴드 터치 기준)

fetch_screener.py 이후 실행 (crontab 20:50)
55 20 * * 1-5 cd ~/swingfarmer.github.io && python3 scripts/fetch_foreign_flow.py >> ~/cron.log 2>&1
"""

import json, datetime, pathlib, sys, math

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
HIST_FILE = REPO_DIR / "data" / "kr" / "screener" / "investor_hist.json"
DATA_DIR = REPO_DIR / "data" / "dashboard"
OUTPUT_FILE = DATA_DIR / "foreign_flow.json"

TODAY_DASH = datetime.date.today().strftime("%Y-%m-%d")


def load_investor_hist():
    if not HIST_FILE.exists():
        print(f"[ERROR] {HIST_FILE} 없음")
        sys.exit(1)
    with open(HIST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def aggregate(hist):
    """전종목 일별 합산"""
    date_totals = {}
    for code, daily in hist.items():
        for date_str, vals in daily.items():
            if date_str not in date_totals:
                date_totals[date_str] = {"foreign": 0, "institution": 0, "program": 0}
            date_totals[date_str]["foreign"] += vals.get("foreign", 0) or 0
            date_totals[date_str]["institution"] += vals.get("institution", 0) or 0
            date_totals[date_str]["program"] += vals.get("program", 0) or 0

    rows = []
    for date_str in sorted(date_totals.keys()):
        t = date_totals[date_str]
        rows.append({
            "date": date_str,
            "frgn_net_spot": t["foreign"],
            "inst_net_spot": t["institution"],
            "program_net": t["program"],
        })
    return rows


def calc_signals(rows):
    """MA, 볼린저밴드, 연속일수, 시그널 계산"""
    for i, entry in enumerate(rows):
        frgn = entry["frgn_net_spot"] or 0

        # ── 5MA ──
        if i >= 4:
            vals = [rows[j]["frgn_net_spot"] or 0 for j in range(i - 4, i + 1)]
            entry["ma5"] = round(sum(vals) / len(vals))
        else:
            entry["ma5"] = None

        # ── 20MA ──
        if i >= 19:
            vals = [rows[j]["frgn_net_spot"] or 0 for j in range(i - 19, i + 1)]
            ma20 = sum(vals) / len(vals)
            entry["ma20"] = round(ma20)

            # ── 표준편차 + ±2σ 밴드 ──
            variance = sum((v - ma20) ** 2 for v in vals) / len(vals)
            sigma = math.sqrt(variance)
            entry["sigma"] = round(sigma)
            entry["upper_2s"] = round(ma20 + 2 * sigma)
            entry["lower_2s"] = round(ma20 - 2 * sigma)

            # ── 시그널 판별 ──
            if frgn <= entry["lower_2s"]:
                entry["signal"] = "buy"       # 극단 매도 → 역발상 매수
            elif frgn >= entry["upper_2s"]:
                entry["signal"] = "sell"      # 극단 매수 → 과열 경계
            else:
                entry["signal"] = None
        else:
            entry["ma20"] = None
            entry["sigma"] = None
            entry["upper_2s"] = None
            entry["lower_2s"] = None
            entry["signal"] = None

        # ── 연속 매도/매수 일수 ──
        if i == 0:
            if frgn > 0:
                entry["consec_buy"] = 1
                entry["consec_sell"] = 0
            elif frgn < 0:
                entry["consec_buy"] = 0
                entry["consec_sell"] = 1
            else:
                entry["consec_buy"] = 0
                entry["consec_sell"] = 0
        else:
            prev = rows[i - 1]
            if frgn > 0:
                entry["consec_buy"] = prev.get("consec_buy", 0) + 1
                entry["consec_sell"] = 0
            elif frgn < 0:
                entry["consec_buy"] = 0
                entry["consec_sell"] = prev.get("consec_sell", 0) + 1
            else:
                entry["consec_buy"] = 0
                entry["consec_sell"] = 0

    return rows


def save_data(rows):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    latest = rows[-1] if rows else {}
    output = {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "investor_hist.json (KOSPI200 408종목 합산)",
        "unit": "주(수량)",
        "latest": latest,
        "history": rows,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[OK] 저장: {OUTPUT_FILE} ({len(rows)}일)")


def main():
    print(f"=== fetch_foreign_flow.py — {TODAY_DASH} ===")
    hist = load_investor_hist()
    print(f"[INFO] 종목수: {len(hist)}")
    rows = aggregate(hist)
    rows = calc_signals(rows)
    print(f"[INFO] 일수: {len(rows)}")

    if rows:
        lat = rows[-1]
        print(f"[최신] {lat['date']} 외국인={lat['frgn_net_spot']:,}주 기관={lat['inst_net_spot']:,}주")
        print(f"       MA5={lat.get('ma5')} MA20={lat.get('ma20')} σ={lat.get('sigma')}")
        print(f"       밴드=[{lat.get('lower_2s')}, {lat.get('upper_2s')}]")
        print(f"       시그널={lat.get('signal')} 연속매도={lat.get('consec_sell')}일 연속매수={lat.get('consec_buy')}일")

    save_data(rows)


if __name__ == "__main__":
    main()
