#!/usr/bin/env python3
"""
fetch_foreign_flow.py — 외국인/기관 현물 순매수 합산
소스: data/kr/screener/investor_hist.json (fetch_screener.py가 생성)
출력: data/dashboard/foreign_flow.json

fetch_screener.py가 먼저 돌아야 함 (crontab 20:45)
이 스크립트는 그 뒤에 실행 (crontab 20:55)

55 20 * * 1-5 cd /home/opc/swingfarmer.github.io && python3 scripts/fetch_foreign_flow.py >> logs/foreign_flow.log 2>&1
"""

import json, datetime, pathlib, sys

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
    """전종목 일별 합산 → [{date, foreign, institution, program}, ...]"""
    date_totals = {}

    for code, daily in hist.items():
        for date_str, vals in daily.items():
            if date_str not in date_totals:
                date_totals[date_str] = {"foreign": 0, "institution": 0, "program": 0}
            date_totals[date_str]["foreign"] += vals.get("foreign", 0) or 0
            date_totals[date_str]["institution"] += vals.get("institution", 0) or 0
            date_totals[date_str]["program"] += vals.get("program", 0) or 0

    # 날짜순 정렬
    rows = []
    for date_str in sorted(date_totals.keys()):
        t = date_totals[date_str]
        # 단위: 수량(주) → 대시보드에서는 수량 기준으로 표시
        rows.append({
            "date": date_str,
            "frgn_net_spot": t["foreign"],         # 외국인 순매수 (주)
            "inst_net_spot": t["institution"],      # 기관 순매수 (주)
            "program_net": t["program"],            # 프로그램 순매수 (주)
            "frgn_net_fut": None,                   # 선물 (별도 소스 필요)
            "call_net": None,
            "put_net": None,
        })

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
    print(f"[INFO] 일수: {len(rows)}")

    if rows:
        latest = rows[-1]
        print(f"[최신] {latest['date']} 외국인={latest['frgn_net_spot']:,}주 기관={latest['inst_net_spot']:,}주 프로그램={latest['program_net']:,}주")

    save_data(rows)


if __name__ == "__main__":
    main()
