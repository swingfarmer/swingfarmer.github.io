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
    # 미국채 (084)
    ("data/bond/ust_curve.json",           "미국채 금리곡선",   "daily",   0),
    ("data/bond/ust_list.json",            "미국채 목록",       "daily",   0),
    ("data/bond/ktb_curve.json",           "한국 금리(ECOS)",   "weekday", 0),
    # 미국 ETF
    ("data/us_etf.json",                   "미국 ETF",          "weekday", 0),
    ("data/us/index_map.json",             "미국 지수 히트맵",  "weekday", 0),   # (088) 월~토 07:20 — 월요일은 금요일 종가 다시 저장(월요일 경고 방지)
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
    # 국내 ETF (082)
    ("data/kr/etf/latest.json",           "국내 ETF",          "weekday", 0),
    ("data/kr/etf/holdings.json",         "국내 ETF 구성종목", "weekly",  9),
    # 장중 준실시간 — 레포 밖 VM 로컬 파일 (~로 시작하면 홈 기준, 083)
    ("~/sf_live/prices_live.json",        "주식 준실시간",     "weekday", 0),
    ("~/sf_live/etf_live.json",           "국내 ETF 준실시간", "weekday", 0),
    # 선물
    ("data/futures_investor.json",         "선물 투자자별",     "weekday", 0),
    # 시장지표
    ("data/realestate_index.json",         "부동산지표",        "monthly", 35),
    # 주간
    ("data/kr/weekly_ma/latest.json",      "5주선 스크리너",    "weekly",  9),
    ("data/kr/ma_signal/latest.json",      "이평선 시그널",     "weekly",  9),
    ("data/kr/momentum/weekly.json",       "모멘텀(주간)",      "weekly",  9),
    # 뉴스 — (086) 실제 저장 위치는 VM 로컬 ~/news_data (예전 data/news/index.json 은 없는 경로라 11/8부터 매일 "파일 없음" 경고가 났음)
    ("~/news_data/news.json",              "뉴스",             "daily",   0),
    # 미국 지수·VIX·환율 (야후, 086 추가)
    ("data/market_indicators.json",        "시장지표(야후)",    "weekday", 0),
    ("data/market_history.json",           "시장지표 히스토리", "weekday", 0),
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
        # (086) 추가. 금은 미국 전날 종가 날짜라 4일 허용, ECOS는 하루 늦게 올라오는 날이 있어 4일
        ("SELECT MAX(trade_date) FROM daily_prices",  "일봉 (DB)",          "weekday", 0),
        ("SELECT MAX(trade_date) FROM sector_prices", "업종 일봉 (DB)",     "weekday", 0),
        ("SELECT MAX(price_date) FROM gold_prices",   "금 시세(야후, DB)",  "weekday", 4),
        ("SELECT MAX(rate_date) FROM interest_rates", "ECOS 금리 (DB)",     "weekday", 4),
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


# ── (086) 내용이 며칠째 그대로인지 감시 ──
# 파일 갱신 시각만 보면 "스크립트는 돌았는데 소스(야후 등)가 옛 값·빈 값을 준 경우"를 못 잡음.
# 갱신 시각 같은 칸을 빼고 내용 해시를 비교해, 바뀌어야 하는 날이 3번 지나도록 그대로면 경고.
# 상태는 VM 로컬 파일(~/.sf_healthcheck_state.json)에만 저장 — 레포·공개 페이지에 안 올라감.
import hashlib
HASH_STATE = os.path.expanduser("~/.sf_healthcheck_state.json")
HASH_DAYS = 3
HASH_SKIP = {"data/bond/ust_list.json"}          # 월말 기준 목록이라 한 달 내내 같음
VOLATILE_KEYS = {"updated", "generated", "last_updated", "checked_at", "updated_at", "fetched_at", "ts"}

def load_hash_state():
    try:
        with open(HASH_STATE) as f: return json.load(f)
    except Exception: return {}

def save_hash_state(st):
    try:
        with open(HASH_STATE, "w") as f: json.dump(st, f, indent=1)
    except Exception as e:
        print(f"  ⚠ 해시 상태 저장 실패: {e}")

def content_hash(abs_path):
    with open(abs_path, encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, dict):
        d = {k: v for k, v in d.items() if k not in VOLATILE_KEYS}
    return hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

def change_days(since, today, cycle):
    """since 다음 날부터 today까지, 데이터가 바뀌어야 하는 날 수 (weekday면 월~금만)"""
    a = datetime.strptime(since, "%Y-%m-%d"); b = datetime.strptime(today, "%Y-%m-%d")
    n, d = 0, a + timedelta(days=1)
    while d <= b:
        if cycle == "daily" or d.weekday() <= 4: n += 1
        d += timedelta(days=1)
    return n

def check_unchanged(rel_path, abs_path, cycle, st, today):
    """그대로면 (일수, since) 반환, 아니면 None"""
    if cycle not in ("weekday", "daily") or rel_path in HASH_SKIP:
        return None
    try:
        h = content_hash(abs_path)
    except Exception:
        return None
    prev = st.get(rel_path)
    if not prev or prev.get("h") != h:
        st[rel_path] = {"h": h, "since": today}
        return None
    n = change_days(prev["since"], today, cycle)
    return (n, prev["since"]) if n >= HASH_DAYS else None


def check_freshness():
    """각 파일의 freshness 체크. status 리스트 반환."""
    now = datetime.now()
    results = []
    st = load_hash_state(); today = now.strftime("%Y-%m-%d")

    for rel_path, desc, cycle, max_stale_days in TARGETS:
        abs_path = os.path.expanduser(rel_path) if rel_path.startswith('~') else os.path.join(ROOT_DIR, rel_path)
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
                un = check_unchanged(rel_path, abs_path, cycle, st, today)
                if un:
                    entry["status"] = "stale"
                    entry["message"] = f"파일은 갱신되는데 내용이 {un[1]} 이후 그대로 ({un[0]}일) — 소스 주소·차단 확인 (연휴면 무시)"

        results.append(entry)

    save_hash_state(st)
    return results


# ── (085) API 키·계정 만료 감시 ──
# 목록: vm/key_expiry.json (이름·날짜만, 값 없음). 결과는 status.json(공개 페이지)에 안 넣고 텔레그램 DM으로만 보냄.
# 알림: 남은 날 8~30일은 월요일·D-30에만, 7일 이하는 매일, 지난 것도 매일.
KEY_FILE = os.path.join(ROOT_DIR, "vm", "key_expiry.json")

def oracle_admin_expiry():
    """Oracle ADMIN 비번 (상태, 만료일 date|None). 실패 시 (None, None)."""
    try:
        import oracledb
        WALLET_DIR = os.path.expanduser('~/wallet')
        conn = oracledb.connect(
            user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
            dsn='db1007_medium', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
            wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))
        cur = conn.cursor()
        try:
            cur.execute("SELECT account_status, expiry_date FROM dba_users WHERE username='ADMIN'")
        except Exception:
            cur.execute("SELECT account_status, expiry_date FROM user_users")
        r = cur.fetchone()
        conn.close()
        if not r: return (None, None)
        return (r[0], r[1].date() if r[1] else None)
    except Exception as e:
        print(f"  ⚠ Oracle 계정 만료 조회 실패: {str(e)[:120]}")
        return (None, None)

def check_key_expiry(now=None):
    """[(이름, 남은일수|None, 만료일문자열, 연장방법, 알림여부)]"""
    now = now or datetime.now()
    today = now.date()
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            items = json.load(f).get("items", [])
    except Exception as e:
        print(f"  ⚠ key_expiry.json 읽기 실패: {e}")
        return []
    out = []
    for it in items:
        exp = it.get("expires")
        if not exp: continue
        if exp == "db":
            st, d = oracle_admin_expiry()
            if st and st != "OPEN":
                out.append((it["name"], 0, f"상태 {st}", it.get("renew", ""), True)); continue
            if not d:
                out.append((it["name"], None, "만료 없음" if st else "조회 실패", it.get("renew", ""), False)); continue
            exp_d = d
        else:
            try: exp_d = datetime.strptime(exp, "%Y-%m-%d").date()
            except ValueError: continue
        left = (exp_d - today).days
        alert = left <= 7 or (left <= 30 and (today.weekday() == 0 or left == 30))
        out.append((it["name"], left, exp_d.isoformat(), it.get("renew", ""), alert))
    return out

def key_watch_map():
    """healthcheck 항목 이름 → 의심 키 이름 목록"""
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            items = json.load(f).get("items", [])
    except Exception:
        return {}
    m = {}
    for it in items:
        for w in it.get("watch", []): m.setdefault(w, []).append(it["name"])
    return m

def send_key_alert(keys):
    hits = [k for k in keys if k[4]]
    if not hits:
        print("🔑 키 만료 알림 없음"); return
    lines = ["🔑 <b>API 키·계정 만료 임박</b>"]
    for name, left, exp, renew, _ in hits:
        when = "이미 만료" if (left is not None and left < 0) else (f"D-{left}" if left is not None else "")
        lines.append(f"• <b>{name}</b> {when} ({exp})")
        if renew: lines.append(f"   {renew}")
    if send_dm("\n".join(lines)):
        print(f"📱 키 만료 DM 발송 ({len(hits)}건)")
    else:
        print("⚠ 키 만료 DM 발송 실패")


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

    watch = key_watch_map()
    for p in problems:
        icon = "❌" if p["status"] == "missing" else "⏰"
        lines.append(f"{icon} <b>{p['desc']}</b>")
        lines.append(f"   {p['file']}")
        lines.append(f"   {p['message']}")
        if p.get("last_modified"):
            lines.append(f"   최종: {p['last_modified']}")
        if p["desc"] in watch:   # (085) 키·로그인 만료도 의심해볼 것
            lines.append(f"   🔑 키·로그인 확인: {', '.join(watch[p['desc']])}")
        lines.append("")

    msg = "\n".join(lines)
    if send_dm(msg):
        print(f"📱 텔레그램 DM 발송 (문제 {len(problems)}건)")
    else:
        print("⚠ 텔레그램 발송 실패")


def print_keys(keys):
    print("\n🔑 키·계정 만료")
    for name, left, exp, renew, alert in keys:
        tag = "🔔" if alert else "  "
        print(f"  {tag} {name:34s} {exp:>12s}  " + (f"D-{left}" if left is not None and left >= 0 else ("만료" if left is not None else "-")))


def main():
    if "--keys" in sys.argv:   # (085) 만료 목록만 출력 (status.json·텔레그램 안 건드림)
        print_keys(check_key_expiry()); return
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

    # (093) 파일 없음·DB 실패 항목은 last_modified가 None → 예전엔 여기서 TypeError로 죽어서
    #       아래 send_alert까지 못 가고 텔레그램이 아예 안 갔음(11/12 실행). None이면 "-"로 찍고,
    #       찍다가 무슨 에러가 나도 알림은 무조건 보내도록 항목마다 감쌈.
    for r in results:
        try:
            icon = {"ok": "✅", "stale": "⏰", "missing": "❌"}.get(r.get("status"), "?")
            mod = str(r.get("last_modified") or "-")
            print(f"  {icon} {str(r.get('desc')):20s} {mod:>16s}  {r.get('message', '')}")
        except Exception as e:
            print(f"  ? 출력 실패 {r.get('desc')}: {e}")

    send_alert(status)
    keys = check_key_expiry()
    print_keys(keys)
    send_key_alert(keys)
    print(f"\n{'='*50}")
    print("완료!")


if __name__ == "__main__":
    # (093) 헬스체크 자체가 죽으면 "알림 없음 = 정상"으로 착각하게 됨 → 죽었다는 DM을 따로 보냄
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            send_dm(f"🚨 <b>헬스체크 자체 에러</b>\n{type(e).__name__}: {str(e)[:200]}\n로그: tail -40 ~/logs/healthcheck.log")
        except Exception:
            pass
        sys.exit(1)
