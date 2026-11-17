#!/usr/bin/env python3
"""
선물 투자자별 매매동향 + KOSPI200/KOSPI 지수 종가 수집
======================================================
KRX data.krx.co.kr → Oracle FUTURES_INVESTOR 테이블.
pykrx 세션 로그인 후 JSON API 호출.

환경변수 (. ~/.env_secrets):
  KRX_ID, KRX_PW, ORACLE_DB_PASSWORD, ORACLE_WALLET_PASSWORD

사용법:
  python3 scripts/fetch_futures_investor.py              # 최근 5거래일
  python3 scripts/fetch_futures_investor.py --days 30    # 최근 30일
  python3 scripts/fetch_futures_investor.py --backfill 365  # 1년 백필

cron 예시 (평일 18:50):
  50 18 * * 1-5 cd ~/swingfarmer.github.io && . ~/.env_secrets && python3 scripts/fetch_futures_investor.py >> ~/logs/fetch_futures_investor.log 2>&1
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

import oracledb

# ── 환경변수 로드 ──
ENV_FILE = os.path.expanduser("~/.env_secrets")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                key = key.replace('export ', '').strip()
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)

WALLET_DIR = os.path.expanduser("~/wallet")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)

KRX_BLD = "dbms/MDC/STAT/standard/MDCSTAT13102"
KRX_ISU_CD = "KR___FUK2I"


def get_krx_session():
    try:
        from pykrx.website.comm.webio import get_session
        krxs = get_session()
        if krxs is None:
            print("  ❌ KRX 세션 없음 — KRX_ID/KRX_PW 확인")
            sys.exit(1)
        return krxs
    except Exception as e:
        print(f"  ❌ pykrx 로그인 실패: {e}")
        sys.exit(1)


def _krx_headers(krxs):
    headers = krxs.get_headers()
    headers["User-Agent"] = "Mozilla/5.0"
    headers["Referer"] = "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd"
    headers["X-Requested-With"] = "XMLHttpRequest"
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    return headers


def fetch_krx_data(krxs, start_date, end_date, prt_type="QTY"):
    resp = krxs.session.post(
        "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
        headers=_krx_headers(krxs),
        data={
            "bld": KRX_BLD, "locale": "ko_KR", "prodId": "",
            "strtDd": start_date, "endDd": end_date,
            "inqTpCd": "2", "prtType": prt_type, "prtCheck": "SUN",
            "isuCd": KRX_ISU_CD, "aggBasTpCd": "",
            "strtDdBox1": start_date, "endDdBox1": end_date,
            "money": "3", "csvxls_isNo": "false"
        }
    )
    if resp.status_code != 200:
        print(f"  ❌ HTTP {resp.status_code}")
        return []
    try:
        return resp.json().get("output", [])
    except Exception as e:
        print(f"  ❌ JSON 파싱 실패: {e}")
        return []


def fetch_index_close(start_date, end_date, ticker="1028", name="KOSPI200"):
    """pykrx로 지수 종가 조회 → {YYYYMMDD: close_price} dict."""
    result = {}
    try:
        from pykrx import stock as pykrx_stock
        df = pykrx_stock.get_index_ohlcv_by_date(start_date, end_date, ticker)
        if df is not None and len(df) > 0:
            for idx_date, row in df.iterrows():
                dt = idx_date.strftime("%Y%m%d")
                close = float(row["종가"])
                if close > 0:
                    result[dt] = close
    except Exception as e:
        print(f"  ⚠ {name} pykrx 조회 실패: {e}")
    print(f"  📈 {name} 종가: {len(result)}일치")
    return result


def parse_number(s):
    if not s or s.strip() == "":
        return 0
    return int(s.replace(",", ""))


def save_to_oracle(rows_qty, rows_amt, kospi200_map=None, kospi_map=None):
    if kospi200_map is None: kospi200_map = {}
    if kospi_map is None: kospi_map = {}

    conn = oracledb.connect(
        user="ADMIN",
        password=os.environ.get("ORACLE_DB_PASSWORD", ""),
        dsn="db1007_medium",
        config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=os.environ.get("ORACLE_WALLET_PASSWORD", "")
    )
    cur = conn.cursor()

    # 테이블 생성
    try:
        cur.execute("""CREATE TABLE futures_investor (
            trade_date    DATE NOT NULL,
            institution_qty   NUMBER(12), corp_other_qty NUMBER(12),
            individual_qty    NUMBER(12), foreign_qty    NUMBER(12),
            institution_amt   NUMBER(18), corp_other_amt NUMBER(18),
            individual_amt    NUMBER(18), foreign_amt    NUMBER(18),
            kospi200_close    NUMBER(10,2),
            kospi_close       NUMBER(10,2),
            CONSTRAINT pk_futures_investor PRIMARY KEY (trade_date)
        )""")
        conn.commit()
        print("  ✅ 테이블 생성: FUTURES_INVESTOR")
    except Exception:
        pass

    # 컬럼 추가 (기존 테이블용)
    for col in ['kospi200_close', 'kospi_close']:
        try:
            cur.execute(f"ALTER TABLE futures_investor ADD ({col} NUMBER(10,2))")
            conn.commit()
            print(f"  ✅ 컬럼 추가: {col}")
        except Exception:
            pass

    # 데이터 병합
    date_data = {}
    for row in rows_qty:
        dt = row["TRD_DD"].replace("/", "")
        date_data.setdefault(dt, {})
        date_data[dt]["institution_qty"] = parse_number(row.get("A07", ""))
        date_data[dt]["corp_other_qty"] = parse_number(row.get("A08", ""))
        date_data[dt]["individual_qty"] = parse_number(row.get("A09", ""))
        date_data[dt]["foreign_qty"] = parse_number(row.get("A12", ""))

    for row in rows_amt:
        dt = row["TRD_DD"].replace("/", "")
        date_data.setdefault(dt, {})
        date_data[dt]["institution_amt"] = parse_number(row.get("A07", ""))
        date_data[dt]["corp_other_amt"] = parse_number(row.get("A08", ""))
        date_data[dt]["individual_amt"] = parse_number(row.get("A09", ""))
        date_data[dt]["foreign_amt"] = parse_number(row.get("A12", ""))

    for dt in date_data:
        date_data[dt]["kospi200_close"] = kospi200_map.get(dt)
        date_data[dt]["kospi_close"] = kospi_map.get(dt)

    saved = 0
    for dt, d in date_data.items():
        try:
            cur.execute("""MERGE INTO futures_investor t
                USING (SELECT TO_DATE(:dt,'YYYYMMDD') AS trade_date FROM dual) s
                ON (t.trade_date = s.trade_date)
                WHEN MATCHED THEN UPDATE SET
                    institution_qty = :iq, corp_other_qty = :cq,
                    individual_qty = :pq, foreign_qty = :fq,
                    institution_amt = :ia, corp_other_amt = :ca,
                    individual_amt = :pa, foreign_amt = :fa,
                    kospi200_close = NVL(:kc, t.kospi200_close),
                    kospi_close = NVL(:kk, t.kospi_close)
                WHEN NOT MATCHED THEN INSERT
                    (trade_date, institution_qty, corp_other_qty,
                     individual_qty, foreign_qty,
                     institution_amt, corp_other_amt,
                     individual_amt, foreign_amt,
                     kospi200_close, kospi_close)
                VALUES (TO_DATE(:dt,'YYYYMMDD'), :iq, :cq, :pq, :fq,
                        :ia, :ca, :pa, :fa, :kc, :kk)
            """, {
                "dt": dt,
                "iq": d.get("institution_qty", 0), "cq": d.get("corp_other_qty", 0),
                "pq": d.get("individual_qty", 0), "fq": d.get("foreign_qty", 0),
                "ia": d.get("institution_amt", 0), "ca": d.get("corp_other_amt", 0),
                "pa": d.get("individual_amt", 0), "fa": d.get("foreign_amt", 0),
                "kc": d.get("kospi200_close"), "kk": d.get("kospi_close")
            })
            saved += 1
        except Exception as e:
            print(f"  ❌ {dt}: {e}")

    conn.commit()
    cur.execute("""SELECT COUNT(*), MIN(TO_CHAR(trade_date,'YYYY-MM-DD')),
        MAX(TO_CHAR(trade_date,'YYYY-MM-DD')),
        COUNT(kospi200_close), COUNT(kospi_close)
        FROM futures_investor""")
    cnt, mn, mx, k2cnt, kcnt = cur.fetchone()
    print(f"  📊 DB: {cnt}일치 ({mn}~{mx}), K200:{k2cnt}일, KOSPI:{kcnt}일")
    cur.close(); conn.close()
    return saved


def export_json(conn_params=None):
    conn = oracledb.connect(
        user="ADMIN", password=os.environ.get("ORACLE_DB_PASSWORD", ""),
        dsn="db1007_medium", config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=os.environ.get("ORACLE_WALLET_PASSWORD", "")
    )
    cur = conn.cursor()
    cur.execute("""SELECT TO_CHAR(trade_date,'YYYY-MM-DD') AS dt,
        institution_qty, corp_other_qty, individual_qty, foreign_qty,
        institution_amt, corp_other_amt, individual_amt, foreign_amt,
        kospi200_close, kospi_close
        FROM futures_investor ORDER BY trade_date""")
    cols = [c[0].lower() for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close(); conn.close()
    out_path = os.path.join(ROOT_DIR, "data", "futures_investor.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, default=str)
    print(f"  📁 JSON: {out_path} ({len(rows)}일치, {os.path.getsize(out_path)/1024:.1f}KB)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--backfill", type=int, help="백필 일수")
    args = parser.parse_args()

    days = args.backfill or args.days
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days + 10)
    start_str = start_dt.strftime("%Y%m%d")
    end_str = end_dt.strftime("%Y%m%d")

    print(f"📊 선물 투자자별 + KOSPI200/KOSPI 종가 수집")
    print(f"   기간: {start_str} ~ {end_str}")

    # 1. KRX 로그인
    krxs = get_krx_session()
    print("  ✅ KRX 로그인 완료")

    # 2. 투자자별 데이터
    chunk_size = 365
    all_qty, all_amt = [], []
    cur_start = start_dt
    while cur_start < end_dt:
        cur_end = min(cur_start + timedelta(days=chunk_size), end_dt)
        s, e = cur_start.strftime("%Y%m%d"), cur_end.strftime("%Y%m%d")
        print(f"  📥 {s}~{e} (QTY)...", end="", flush=True)
        qty = fetch_krx_data(krxs, s, e, "QTY")
        print(f" {len(qty)}건"); all_qty.extend(qty); time.sleep(1)
        print(f"  📥 {s}~{e} (AMT)...", end="", flush=True)
        amt = fetch_krx_data(krxs, s, e, "AMT")
        print(f" {len(amt)}건"); all_amt.extend(amt); time.sleep(1)
        cur_start = cur_end + timedelta(days=1)

    if not all_qty:
        print("  ⚠ 데이터 없음"); return

    # 3. 지수 종가 (pykrx — KRX 로그인 불필요)
    kospi200_map = fetch_index_close(start_str, end_str, "1028", "KOSPI200")
    time.sleep(1)
    kospi_map = fetch_index_close(start_str, end_str, "1001", "KOSPI")
    time.sleep(1)

    # 4. Oracle 저장
    saved = save_to_oracle(all_qty, all_amt, kospi200_map, kospi_map)
    print(f"  ✅ {saved}일치 저장/갱신")

    # 5. JSON
    export_json()
    print(f"\n{'='*50}\n✅ 완료")


if __name__ == "__main__":
    main()
