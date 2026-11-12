"""
한국 금리(국고채 만기별 + 기준금리·CD·CP·회사채) → data/bond/ktb_curve.json (084)
==========================================================================
fetch_ecos.py가 Oracle INTEREST_RATES(data_type='ECOS')에 넣은 값을 꺼내
/bond/ 페이지가 읽는 작은 JSON으로 바꿈. 외부 호출 없음(DB만 읽음).
작년 1월 1일부터. 미국채 파일(ust_curve.json)과 같은 모양.
오라클 cron 평일 18:10 fetch_ecos.py 바로 뒤에 이어서 실행.

사용:
  python3 scripts/export_ktb.py          # 저장
  python3 scripts/export_ktb.py --test   # 항목별 개수·기간만 출력, 저장 안 함
"""
import json, os, sys
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
OUT = os.path.join(ROOT_DIR, "data", "bond", "ktb_curve.json")
TEST = "--test" in sys.argv

# (이름, INTEREST_RATES.item_code)  — fetch_ecos.py INDICATORS와 같은 코드 (통계표_항목)
TENORS = [("1Y", "817Y002_010190000"), ("3Y", "817Y002_010200000"), ("5Y", "817Y002_010200001"),
          ("10Y", "817Y002_010210000"), ("20Y", "817Y002_010220000"), ("30Y", "817Y002_010230000")]
EXTRA = [("기준금리", "722Y001_0101000"), ("CD91일", "817Y002_010502000"), ("CP91일", "817Y002_010503000"),
         ("회사채AA-3Y", "817Y002_010300000"), ("회사채BBB-3Y", "817Y002_010320000")]


def log(m):
    print(f"{datetime.now(KST).strftime('%H:%M:%S')} {m}", flush=True)


def get_conn():
    import oracledb
    w = os.path.expanduser("~/wallet")
    return oracledb.connect(user="ADMIN", password=os.environ.get("ORACLE_DB_PASSWORD", ""),
                            dsn="db1007_medium", config_dir=w, wallet_location=w,
                            wallet_password=os.environ.get("ORACLE_WALLET_PASSWORD", ""))


def build(db_rows, start):
    """[(날짜, 코드, 값)] → rows [[날짜, 값...]] (국고채 3년 값이 있는 날만)."""
    names = TENORS + EXTRA
    idx = {code: i for i, (_, code) in enumerate(names)}
    by = {}
    for d, code, v in db_rows:
        if d < start or code not in idx or v is None:
            continue
        by.setdefault(d, [None] * len(names))[idx[code]] = round(float(v), 3)
    i3 = idx["817Y002_010200000"]
    rows, last = [], [None] * len(names)
    for d in sorted(by):
        vals = by[d]
        # 기준금리는 바뀐 날만 있을 수 있음 → 직전 값 이어 씀
        for j, (nm, _) in enumerate(names):
            if vals[j] is None and nm == "기준금리":
                vals[j] = last[j]
        last = [vals[j] if vals[j] is not None else last[j] for j in range(len(names))]
        if vals[i3] is not None:
            rows.append([d] + vals)
    return rows


def main():
    log("🇰🇷 한국 금리 내보내기" + (" (--test)" if TEST else ""))
    start = f"{datetime.now(KST).year - 1}-01-01"
    codes = [c for _, c in TENORS + EXTRA]
    conn = get_conn(); cur = conn.cursor()
    ph = ",".join(f":c{i}" for i in range(len(codes)))
    params = {f"c{i}": c for i, c in enumerate(codes)}
    # 기준금리는 날짜가 띄엄띄엄이라 시작일 전 마지막 값도 필요 → 1년 더 앞부터 읽음
    params["df"] = f"{datetime.now(KST).year - 2}-01-01"
    cur.execute(f"""SELECT TO_CHAR(rate_date,'YYYY-MM-DD'), item_code, rate FROM interest_rates
                    WHERE data_type='ECOS' AND item_code IN ({ph}) AND rate_date >= TO_DATE(:df,'YYYY-MM-DD')
                    ORDER BY rate_date""", params)
    db_rows = cur.fetchall()
    cur.close(); conn.close()

    cnt = {}
    for d, c, v in db_rows:
        x = cnt.setdefault(c, [0, d, d]); x[0] += 1; x[2] = d
    for nm, c in TENORS + EXTRA:
        x = cnt.get(c)
        log(f"  {nm:12s} {c}: " + (f"{x[0]}건 {x[1]} ~ {x[2]}" if x else "❌ 없음"))

    # 기준금리 이어쓰기용으로 앞쪽 값까지 넣고 만든 뒤 시작일 이후만 남김
    rows = [r for r in build(db_rows, params["df"]) if r[0] >= start]
    if len(rows) < 50:
        log(f"❌ 행이 너무 적음 ({len(rows)}) — fetch_ecos.py --backfill 필요할 수 있음. 저장 안 함")
        sys.exit(1)
    obj = {"date": rows[-1][0], "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
           "src": "한국은행 ECOS 시장금리(일별) — fetch_ecos.py → Oracle", "unit": "%",
           "tenors": [n for n, _ in TENORS], "extra": [n for n, _ in EXTRA], "rows": rows}
    log(f"✅ {len(rows)}일 / {rows[0][0]} ~ {rows[-1][0]} / 최근 {rows[-1]}")
    age = (datetime.now(KST).date() - datetime.strptime(obj["date"], "%Y-%m-%d").date()).days
    if age > 6:
        log(f"⚠ 최근 날짜가 {age}일 전")
    if TEST:
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT)
    log(f"💾 data/bond/ktb_curve.json ({os.path.getsize(OUT)//1024}KB)")


if __name__ == "__main__":
    main()
