#!/usr/bin/env python3
"""
위기 비교용 원자료 받기 — 읽기 전용 (112 → 126 확장)
=====================================================
코스피(KRX 1001, 1980~)와 해외 지수·금리·환율·유가 일별 종가를 받아
레포 루트 `_tmp_crisis.csv` 한 파일로만 저장한다(공개 시세, 분석 끝나면 바로 git rm).
DB·다른 파일에는 아무것도 안 씀.

열: kospi / spx(^GSPC) vix(^VIX) tnx(^TNX 10년물) — 112부터
    (126) ixic(나스닥 종합) sox(필라델피아 반도체) sse(상하이 000001.SS) twii(대만 가권)
          n225(닛케이 — 1990 일본 L자 비교) dxy(달러인덱스)
          krw(원/달러, FRED DEXKOUS 1981~) irx(미 3개월, FRED DTB3 1954~) wti(FRED DCOILWTICO 1986~)
    (134) fed(미 기준금리 목표 — FRED DFEDTAR 1982~2008.12 + DFEDTARU 상단 2008.12~)
          bok(한국은행 기준금리 — ECOS 722Y001/0101000 1999.5~, ECOS_API_KEY 필요)
    FRED가 막히면 야후(KRW=X·^IRX·CL=F)로 대신 받음. 한 열이 실패해도 나머지는 저장.

  . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/crisis_probe.py
"""
import csv
import json
import os
import ssl
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import yfinance as yf
from pykrx import stock

KST = timezone(timedelta(hours=9))
END = datetime.now(KST).strftime("%Y%m%d")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_tmp_crisis.csv")


def kospi():
    """KRX 코스피 지수 일별 종가 — 5년씩 나눠 받음."""
    out = {}
    for y in range(1980, int(END[:4]) + 1, 5):
        s, e = f"{y}0101", min(f"{y + 4}1231", END)
        for k in range(3):
            try:
                df = stock.get_index_ohlcv(s, e, "1001")
                break
            except Exception as ex:
                print(f"  재시도 {s}: {ex}")
                time.sleep(3)
        else:
            df = None
        n = 0
        if df is not None:
            for d, row in df.iterrows():
                c = float(row["종가"])
                if c > 0:
                    out[d.strftime("%Y-%m-%d")] = c
                    n += 1
        print(f"  코스피 {s}~{e}: {n}일")
        time.sleep(1)
    return out


def yahoo(t):
    df = yf.Ticker(t).history(period="max", auto_adjust=False)
    out = {}
    for d, row in df.iterrows():
        c = float(row["Close"])
        if c > 0:
            out[d.strftime("%Y-%m-%d")] = c
    print(f"  {t}: {len(out)}일 ({min(out) if out else '-'} ~ {max(out) if out else '-'})")
    return out


def fred(sid):
    """FRED 공개 csv (키 필요 없음). 값 '.'(휴장)은 뺌."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    txt = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
    out = {}
    for line in txt.splitlines()[1:]:
        p = line.split(",")
        if len(p) == 2 and p[1] not in (".", ""):
            v = float(p[1])
            if v > 0:
                out[p[0]] = v
    print(f"  FRED {sid}: {len(out)}일 ({min(out) if out else '-'} ~ {max(out) if out else '-'})")
    return out


def fed(_):
    """(134) 미 기준금리 목표: 2008.12.15까지 DFEDTAR, 그 뒤 DFEDTARU(범위 상단)."""
    a = fred("DFEDTAR")
    b = fred("DFEDTARU")
    out = {d: v for d, v in a.items() if d <= "2008-12-15"}
    out.update({d: v for d, v in b.items() if d > "2008-12-15"})
    return out


def bok(_):
    """(134) 한국은행 기준금리(일별) — ECOS. 키는 ~/.env_secrets ECOS_API_KEY."""
    key = os.environ.get("ECOS_API_KEY", "")
    if not key:
        print("  ❌ ECOS_API_KEY 없음 — . ~/.env_secrets 먼저")
        return {}
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/100000/"
           f"722Y001/D/19990101/{END}/0101000")
    raw = urllib.request.urlopen(url, timeout=60, context=ssl.create_default_context()).read()
    data = json.loads(raw.decode("utf-8"))
    rows = data.get("StatisticSearch", {}).get("row", [])
    if not rows:
        print(f"  ❌ ECOS 응답: {str(data.get('RESULT', data))[:120]}")
    out = {}
    for r in rows:
        t, v = r.get("TIME", ""), r.get("DATA_VALUE", "")
        if len(t) == 8 and v not in ("", None):
            out[f"{t[:4]}-{t[4:6]}-{t[6:]}"] = float(v)
    print(f"  ECOS 기준금리: {len(out)}일 ({min(out) if out else '-'} ~ {max(out) if out else '-'})")
    return out


def safe(fn, arg):
    try:
        return fn(arg)
    except Exception as ex:
        print(f"  ❌ {arg}: {ex}")
        return {}


# (열 이름, 받는 법) — 앞쪽이 실패하면 뒤쪽으로
SERIES = [
    ("spx", [(yahoo, "^GSPC")]),
    ("vix", [(yahoo, "^VIX")]),
    ("tnx", [(yahoo, "^TNX")]),
    ("ixic", [(yahoo, "^IXIC")]),
    ("sox", [(yahoo, "^SOX")]),
    ("sse", [(yahoo, "000001.SS")]),
    ("twii", [(yahoo, "^TWII")]),
    ("n225", [(yahoo, "^N225")]),
    ("dxy", [(yahoo, "DX-Y.NYB")]),
    ("krw", [(fred, "DEXKOUS"), (yahoo, "KRW=X")]),
    ("irx", [(fred, "DTB3"), (yahoo, "^IRX")]),
    ("wti", [(fred, "DCOILWTICO"), (yahoo, "CL=F")]),
    ("fed", [(fed, "fed")]),
    ("bok", [(bok, "bok")]),
]


def main():
    cols = {"kospi": kospi()}
    for name, ways in SERIES:
        got = {}
        for fn, arg in ways:
            got = safe(fn, arg)
            if got:
                break
        cols[name] = got
        time.sleep(1)
    days = sorted(set().union(*[set(v) for v in cols.values()]))
    names = list(cols)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + names)
        for d in days:
            w.writerow([d] + [cols[n].get(d, "") for n in names])
    print(f"\n저장: {OUT} ({len(days)}줄, {os.path.getsize(OUT) // 1024}KB)")
    for n in names:
        v = cols[n]
        print(f"  {n:6} {min(v) if v else '-'} ~ {max(v) if v else '-'}  {len(v)}일" + ("  ← 비었음" if not v else ""))


if __name__ == "__main__":
    main()
