#!/usr/bin/env python3
"""
위기 발동 조건 백테스트용 원자료 받기 — 읽기 전용 (112)
======================================================
자산배분 노트 5장 「발동 조건」 숫자를 과거 위기에 대 보려고
코스피(KRX 1001, 1980~)·S&P500(^GSPC)·VIX(^VIX)·미국 10년물(^TNX) 일별 종가를 받아
레포 루트 `_tmp_crisis.csv` 한 파일로만 저장한다(공개 시세, 분석 끝나면 바로 git rm).
DB·다른 파일에는 아무것도 안 씀.

  . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/crisis_probe.py
"""
import csv
import os
import time
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


def main():
    k = kospi()
    s = yahoo("^GSPC"); time.sleep(1)
    v = yahoo("^VIX"); time.sleep(1)
    r = yahoo("^TNX")
    days = sorted(set(k) | set(s))
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "kospi", "spx", "vix", "tnx"])
        for d in days:
            w.writerow([d, k.get(d, ""), s.get(d, ""), v.get(d, ""), r.get(d, "")])
    print(f"\n저장: {OUT} ({len(days)}줄, {os.path.getsize(OUT) // 1024}KB)")
    print(f"코스피 {min(k)}~{max(k)} {len(k)}일 / S&P {min(s)}~{max(s)} {len(s)}일")


if __name__ == "__main__":
    main()
