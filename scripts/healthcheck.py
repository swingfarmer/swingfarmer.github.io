#!/usr/bin/env python3
"""
헬스체크 — 데이터 파일 freshness 감시 + 텔레그램 DM 알림 + status.json 생성
==========================================================================
매일 21:30 크론 (모든 수집 크론 이후).
- 각 데이터 파일의 최종 수정 시각을 확인
- 영업일 기준 허용 범위 초과 시 ⚠ 경고
- data/status.json 생성 → /status/ 페이지에서 표시
- 문제 있으면 텔레그램 DM(봇 주인만)으로 알림
"""
import os, json, time, sys
from datetime import datetime, timedelta

# ── 경로 설정 ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data")
sys.path.insert(0, SCRIPT_DIR)

from telegram_helper import send_dm

# ── 모니터링 대상 정의 ──
# (파일 경로, 설명, 주기, 허용 stale 일수)
# 주기: "weekday"=평일만, "daily"=매일, "weekly"=주1회, "monthly"=월1회
TARGETS = [
    # 환율/금리
    ("data/rates.json",                    "환율/금리",         "daily",   0),
    ("data/rates_history.json",            "환율/금리 히스토리", "daily",   0),
    # 미국 ETF
    ("data/us_etf.json",                   "미국 ETF",          "weekday", 0),
    # 종가
    ("data/kr/prices.json",                "종가 수집",         "weekday", 0),
    # 스크리너
    ("data/kr/screener/index.json",        "스크리너",          "weekday", 0),
    # 모멘텀
    ("data/kr/momentum/intraday.json",     "모멘텀(인트라)",    "weekday", 0),
    # 버핏지수
    ("data/buffett.json",                  "버핏지수",          "weekday", 0),
    # 풋콜레이쇼
    ("data/dashboard/putcall.json",        "풋콜레이쇼",        "weekday", 0),
    # 외국인수급
    ("data/dashboard/foreign_flow.json",   "외국인수급 합산",   "weekday", 0),
    # KRX 대시보드
    ("data/krx/investor_top.json",         "KRX 외국인/기관",   "weekday", 0),
    ("data/krx/volume_top.json",           "KRX 거래대금",      "weekday", 0),
    ("data/krx/sector_change.json",        "KRX 업종등락",      "weekday", 0),
    ("data/krx/marketcap_top.json",        "KRX 시총순위",      "weekday", 0),
    ("data/krx/new_high_low.json",         "52주 신고가/신저가", "weekday", 0),
    # 선물
    ("data/futures_investor.json",         "선물 투자자별",     "weekday", 0),
    # 시장지표
    ("data/realestate_index.json",         "부동산지표",        "monthly", 35),
    # 주간
    ("data/kr/weekly_ma/latest.json",      "5주선 스크리너",    "weekly",  9),
    ("data/kr/ma_signal/latest.json",      "이평선 시그널",     "weekly",  9),
    ("data/kr/momentum/weekly.json",       "모멘텀(주간)",      "weekly",  9),
    # 뉴스
    ("data/news/index.json",               "뉴스",             "daily",   0),
    # 매크로
    ("data/macro/sector_etf.json",         "매크로 비교",       "weekday", 0),
]

# 중복 제거
seen = set()
unique_targets = []
for t in TARGETS:
    if t[0] not in seen:
        seen.add(t[0])
        unique_targets.append(t)
TARGETS = unique_targets


def get_effective_max_stale(cycle, max_stale_override, now):
    """요일 기반 동적 stale 허용일수 계산.
    - weekday: 평일만 업데이트 → 월~금은 당일 필수(1), 토(2), 일(3)
    - daily:   매일 업데이트 → 항상 당일 필수(1)
    - weekly/monthly: 고정값 사용 (max_stale_override 그대로)
    """
    if max_stale_override > 0:
        # weekly, monthly 등 고정값이 있는 항목
        return max_stale_override

    dow = now.weekday()  # 0=월 ~ 6=일

    if cycle == "weekday":
        if dow <= 4:    # 월~금: 오늘 업데이트 안 됐으면 알람
            return 1
        elif dow == 5:  # 토: 금요일(1일전) 데이터 허용
            return 2
        else:           # 일: 금요일(2일전) 데이터 허용
            return 3
    elif cycle == "daily":
        return 1        # 매일 업데이트니까 항상 1일
    else:
        return 3        # fallback


def check_db_freshness():
    """Oracle DB 테이블 freshness 체크. status 리스트 반환."""
    DB_TARGETS = [
        # (쿼리, 설명, 주기, 허용 stale 일수 override — 0이면 동적)
        ("SELECT MAX(rate_date) FROM exchange_rates", "수출입은행 환율 (DB)", "weekday", 0),
    ]
    results = []
    try:
        import oracledb
        WALLET_DIR = os.path.expanduser('~/wallet')
        conn = oracledb.connect(
            user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
            dsn='db1007_medium', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
            wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))
        cur = conn.cursor()
        now = datetime.now()
        for query, desc, cycle, max_stale_override in DB_TARGETS:
            max_stale = get_effective_max_stale(cycle, max_stale_override, now)
            entry = {"file": "Oracle DB", "desc": desc, "cycle": cycle, "max_stale_days": max_stale}
            try:
                cur.execute(query)
                row = cur.fetchone()
                if row and row[0]:
                    last_date = row[0]  # DATE 타입
                    if hasattr(last_date, 'strftime'):
                        delta = (now - datetime(last_date.year, last_date.month, last_date.day)).days
                        entry["last_modified"] = last_date.strftime("%Y-%m-%d")
                    else:
                        delta = 999
                        entry["last_modified"] = str(last_date)
                    entry["stale_days"] = delta
                    if delta >= max_stale:
                        entry["status"] = "stale"
                        entry["message"] = f"{delta}일 경과 (허용 {max_stale}일)"
                    else:
                        entry["status"] = "ok"
                        entry["message"] = "정상"
                else:
                    entry["status"] = "missing"
                    entry["message"] = "데이터 없음"
                    entry["last_modified"] = None
                    entry["stale_days"] = None
            except Exception as e:
                entry["status"] = "stale"
                entry["message"] = f"쿼리 실패: {e}"
                entry["last_modified"] = None
                entry["stale_days"] = None
            results.append(entry)
        cur.close()
        conn.close()
    except Exception as e:
        print(f"  ⚠ Oracle DB 연결 실패: {e}")
        now_fb = datetime.now()
        for _, desc, cycle, max_stale_override in DB_TARGETS:
            ms = get_effective_max_stale(cycle, max_stale_override, now_fb)
            results.append({"file": "Oracle DB", "desc": desc, "cycle": cycle,
                            "max_stale_days": ms, "status": "stale",
                            "message": f"DB 연결 실패: {e}", "last_modified": None, "stale_days": None})
    return results


def check_freshness():
    """각 파일의 freshness 체크. status 리스트 반환."""
    now = datetime.now()
    results = []

    for rel_path, desc, cycle, max_stale_days in TARGETS:
        abs_path = os.path.join(ROOT_DIR, rel_path)
        effective_max = get_effective_max_stale(cycle, max_stale_days, now)
        entry = {
            "file": rel_path,
            "desc": desc,
            "cycle": cycle,
            "max_stale_days": effective_max,
        }

        if not os.path.exists(abs_path):
            entry["status"] = "missing"
            entry["message"] = "파일 없음"
            entry["last_modified"] = None
            entry["stale_days"] = None
        else:
            mtime = os.path.getmtime(abs_path)
            last_mod = datetime.fromtimestamp(mtime)
            delta = now - last_mod
            stale_days = delta.days

            entry["last_modified"] = last_mod.strftime("%Y-%m-%d %H:%M")
            entry["stale_days"] = stale_days
            entry["size_kb"] = round(os.path.getsize(abs_path) / 1024, 1)

            # date 필드 읽기 시도
            try:
                with open(abs_path) as f:
                    d = json.load(f)
                if isinstance(d, dict) and "date" in d:
                    entry["data_date"] = d["date"]
            except Exception:
                pass

            if stale_days >= effective_max:
                entry["status"] = "stale"
                entry["message"] = f"{stale_days}일 경과 (허용 {effective_max}일)"
            else:
                entry["status"] = "ok"
                entry["message"] = "정상"

        results.append(entry)

    return results


def build_status_json(results):
    """status.json 생성 + 일자별 히스토리 저장."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    status = {
        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results),
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "stale": sum(1 for r in results if r["status"] == "stale"),
        "missing": sum(1 for r in results if r["status"] == "missing"),
        "items": results,
    }

    # status.json (최신)
    out_path = os.path.join(DATA_DIR, "status.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    print(f"💾 status.json 저장 ({len(results)}건)")

    # 일자별 히스토리 — data/status_history.json
    # 구조: { "dates": ["2026-10-31", ...], "daily": { "2026-10-31": { ok, stale, missing, problems: [...] }, ... } }
    hist_path = os.path.join(DATA_DIR, "status_history.json")
    try:
        with open(hist_path) as f:
            hist = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        hist = {"dates": [], "daily": {}}

    # 오늘자 기록
    problems = [{"desc": r["desc"], "file": r["file"], "message": r["message"]}
                for r in results if r["status"] != "ok"]
    hist["daily"][today] = {
        "ok": status["ok"],
        "stale": status["stale"],
        "missing": status["missing"],
        "problems": problems,
    }
    if today not in hist["dates"]:
        hist["dates"].append(today)
    hist["dates"].sort()

    # 90일 롤링
    if len(hist["dates"]) > 90:
        old = hist["dates"][:-90]
        for d in old:
            hist["daily"].pop(d, None)
        hist["dates"] = hist["dates"][-90:]

    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    print(f"📅 status_history.json 저장 ({len(hist['dates'])}일)")

    return status


def send_alert(status):
    """문제 있으면 텔레그램 DM 알림."""
    problems = [r for r in status["items"] if r["status"] != "ok"]
    if not problems:
        print("✅ 전체 정상 — 알림 없음")
        return

    lines = [f"⚠️ <b>데이터 헬스체크 경고</b> ({status['checked_at'][:10]})"]
    lines.append(f"문제: {len(problems)}건 / 전체 {status['total']}건\n")

    for p in problems:
        icon = "❌" if p["status"] == "missing" else "⏰"
        lines.append(f"{icon} <b>{p['desc']}</b>")
        lines.append(f"   {p['file']}")
        lines.append(f"   {p['message']}")
        if p.get("last_modified"):
            lines.append(f"   최종: {p['last_modified']}")
        lines.append("")

    msg = "\n".join(lines)
    if send_dm(msg):
        print(f"📱 텔레그램 DM 발송 (문제 {len(problems)}건)")
    else:
        print("⚠ 텔레그램 발송 실패")


def main():
    print(f"\n{'='*50}")
    print(f"헬스체크 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"{'='*50}\n")

    results = check_freshness()
    results += check_db_freshness()
    status = build_status_json(results)

    ok = status["ok"]
    stale = status["stale"]
    missing = status["missing"]
    total = status["total"]

    print(f"\n✅ 정상: {ok}  ⏰ 지연: {stale}  ❌ 없음: {missing}  (총 {total})\n")

    for r in results:
        icon = {"ok": "✅", "stale": "⏰", "missing": "❌"}[r["status"]]
        mod = r.get("last_modified", "-")
        print(f"  {icon} {r['desc']:20s} {mod:>16s}  {r['message']}")

    send_alert(status)
    print(f"\n{'='*50}")
    print("완료!")


if __name__ == "__main__":
    main()
