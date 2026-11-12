"""
미국채 금리곡선 + 국채 목록 수집 (084)
======================================
① 재무부 일별 par 금리곡선 CSV (올해 + 작년) → data/bond/ust_curve.json
② 재무부 MSPD(월말 기준 발행 잔액표) Notes·Bonds → data/bond/ust_list.json
   - 재발행(reopening)은 CUSIP 하나로 합침: 최초 발행일, 잔액(백만달러)
   - 만기 지난 것 제외. TIPS·FRN·Bills는 1차에서 제외
오라클 cron 매일 07:10 (auto_push 07:30 전). 키 필요 없음.
실패하면 기존 파일을 덮어쓰지 않고 봇1로 알림.

사용:
  python3 scripts/fetch_ust.py          # 수집 + 저장
  python3 scripts/fetch_ust.py --test   # 수집만, 저장 안 함 (요약 출력)
"""
import csv, io, json, os, sys, urllib.request
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(ROOT_DIR, "data", "bond")
CURVE_FILE = os.path.join(OUT_DIR, "ust_curve.json")
LIST_FILE = os.path.join(OUT_DIR, "ust_list.json")

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
CURVE_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
             "daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&_format=csv")
MSPD_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_3_market"

# CSV 머리글 → 표준 만기 이름 (없는 칸은 null)
TENORS = ["1M", "1.5M", "2M", "3M", "4M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
HEAD_MAP = {"1 Mo": "1M", "1.5 Month": "1.5M", "1.5 Mo": "1.5M", "2 Mo": "2M", "3 Mo": "3M", "4 Mo": "4M",
            "6 Mo": "6M", "1 Yr": "1Y", "2 Yr": "2Y", "3 Yr": "3Y", "5 Yr": "5Y", "7 Yr": "7Y",
            "10 Yr": "10Y", "20 Yr": "20Y", "30 Yr": "30Y"}
TYPE_MAP = {"Notes": "N", "Bonds": "B"}

TEST = "--test" in sys.argv


def log(msg):
    print(f"{datetime.now(KST).strftime('%H:%M:%S')} {msg}", flush=True)


def http_get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8-sig", errors="replace")


# ── ① 금리곡선 ──
def parse_curve_csv(text):
    """CSV 텍스트 → {날짜: [TENORS 순서 값]}. 머리글이 Date로 시작 안 하면 에러."""
    rd = csv.reader(io.StringIO(text))
    head = next(rd, None)
    if not head or head[0].strip().lstrip("\ufeff") != "Date":
        raise ValueError(f"CSV 형식 아님: {text[:120]!r}")
    idx = {}
    for i, h in enumerate(head[1:], 1):
        t = HEAD_MAP.get(h.strip())
        if t:
            idx[t] = i
    out = {}
    for row in rd:
        if not row or not row[0].strip():
            continue
        m, d, y = row[0].strip().split("/")
        date = f"{y}-{int(m):02d}-{int(d):02d}"
        vals = []
        for t in TENORS:
            i = idx.get(t)
            v = row[i].strip() if i is not None and i < len(row) else ""
            try:
                vals.append(round(float(v), 3) if v and v.upper() != "N/A" else None)
            except ValueError:
                vals.append(None)
        out[date] = vals
    return out


def fetch_curve():
    year = datetime.now(KST).year
    merged = {}
    for y in (year - 1, year):
        try:
            part = parse_curve_csv(http_get(CURVE_URL.format(y=y)))
            log(f"  금리곡선 {y}년 {len(part)}일")
            merged.update(part)
        except Exception as e:
            # 1월 초엔 올해 파일이 비었을 수 있음 → 작년만 있어도 진행
            log(f"  ⚠ 금리곡선 {y}년 실패: {e}")
    rows = [[d] + merged[d] for d in sorted(merged)]
    if len(rows) < 20:
        raise RuntimeError(f"금리곡선 행이 너무 적음 ({len(rows)})")
    return {"date": rows[-1][0], "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
            "src": "U.S. Treasury Daily Par Yield Curve", "tenors": TENORS, "rows": rows}


# ── ② MSPD 국채 목록 ──
def fetch_json(url):
    d = json.loads(http_get(url))
    if "data" not in d:
        raise RuntimeError(f"API 에러: {str(d)[:200]}")
    return d["data"]


def num(v):
    try:
        return float(v) if v not in (None, "", "null") else None
    except ValueError:
        return None


def build_list(rows, today):
    """MSPD 행들 → CUSIP 하나당 한 줄. [cusip, 종류, 쿠폰%, 최초발행일, 만기일, 잔액(백만달러)]"""
    g = {}
    for r in rows:
        typ = TYPE_MAP.get(r.get("security_class1_desc"))
        cusip = (r.get("security_class2_desc") or "").strip()
        if not typ or len(cusip) != 9:
            continue
        x = g.setdefault(cusip, {"t": typ, "c": None, "i": None, "m": None, "out": None, "iss": 0.0})
        c = num(r.get("interest_rate_pct"))
        if c is not None:
            x["c"] = c
        if r.get("issue_date") and (x["i"] is None or r["issue_date"] < x["i"]):
            x["i"] = r["issue_date"]
        x["m"] = r.get("maturity_date") or x["m"]
        o = num(r.get("outstanding_amt"))
        if o is not None:
            x["out"] = max(x["out"] or 0, o)
        x["iss"] += (num(r.get("issued_amt")) or 0) - (num(r.get("redeemed_amt")) or 0)
    out = []
    for cusip, x in g.items():
        if not x["m"] or x["m"] <= today or x["c"] is None:
            continue
        amt = x["out"] if x["out"] is not None else x["iss"]
        out.append([cusip, x["t"], x["c"], x["i"], x["m"], round(amt, 1)])
    out.sort(key=lambda r: (r[4], r[2]))
    return out


def fetch_list():
    latest = fetch_json(MSPD_URL + "?sort=-record_date&page[size]=1&fields=record_date")
    rec = latest[0]["record_date"]
    data = fetch_json(MSPD_URL + f"?filter=record_date:eq:{rec},security_class1_desc:in:(Notes,Bonds)&page[size]=10000")
    log(f"  MSPD 기준일 {rec} / 원본 {len(data)}행")
    today = datetime.now(KST).strftime("%Y-%m-%d")
    rows = build_list(data, today)
    if len(rows) < 200:
        raise RuntimeError(f"국채 목록이 너무 적음 ({len(rows)})")
    return {"date": rec, "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
            "src": "U.S. Treasury MSPD Table 3 (Marketable)", "n": len(rows),
            "cols": ["cusip", "type(N/B)", "coupon%", "first_issue", "maturity", "outstanding_mil_usd"],
            "rows": rows}


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    log(f"💾 {os.path.relpath(path, ROOT_DIR)} ({os.path.getsize(path)//1024}KB)")


def alert(msg):
    if TEST:
        return
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from telegram_helper import send_dm
        send_dm(f"⚠️ 미국채 수집 실패 (fetch_ust.py)\n{msg}")
    except Exception as e:
        log(f"  텔레그램 실패: {e}")


def main():
    log("🇺🇸 미국채 수집 시작" + (" (--test, 저장 안 함)" if TEST else ""))
    errors = []

    try:
        cv = fetch_curve()
        last = cv["rows"][-1]
        y10 = last[1 + TENORS.index("10Y")]
        log(f"✅ 금리곡선 {len(cv['rows'])}일 / 최근 {cv['date']} 10Y {y10}%")
        age = (datetime.now(KST).date() - datetime.strptime(cv["date"], "%Y-%m-%d").date()).days
        if age > 6:
            errors.append(f"금리곡선 최근 날짜가 {age}일 전 ({cv['date']})")
        if not TEST:
            save(CURVE_FILE, cv)
    except Exception as e:
        log(f"❌ 금리곡선: {e}")
        errors.append(f"금리곡선: {e}")

    try:
        ls = fetch_list()
        rows = ls["rows"]
        nN = sum(1 for r in rows if r[1] == "N")
        low = sum(1 for r in rows if r[2] <= 2.0)
        log(f"✅ 국채 목록 {len(rows)}종 (Notes {nN} / Bonds {len(rows)-nN}) / 쿠폰 2% 이하 {low}종")
        for r in rows[:2] + rows[-2:]:
            log(f"   예: {r}")
        if not TEST:
            save(LIST_FILE, ls)
    except Exception as e:
        log(f"❌ 국채 목록: {e}")
        errors.append(f"국채 목록: {e}")

    if errors:
        alert("\n".join(errors))
        log("⚠ 끝 (일부 실패)")
        sys.exit(1)
    log("✅ 완료")


if __name__ == "__main__":
    main()
