#!/usr/bin/env python3
"""
코스피 업종지수 일별 종가 받기 — 읽기 전용 (134)
================================================
금리·환율 국면별로 「원화 강세 수혜 업종」(항공·운수창고·음식료·전기가스·은행)과
「원화 약세 수혜 업종」(운수장비·전기전자·조선 포함 기계·화학) 성적을 비교하려고 만듦.

레포 루트 `_tmp_sector.csv` 한 파일로만 저장(공개 시세, 분석 끝나면 바로 git rm).
DB·다른 파일에는 아무것도 안 씀.

  . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/sector_probe.py

먼저 KRX 코스피 지수 목록(코드·이름)을 출력하고, 아래 WANT 이름이 들어간 지수만 받는다.
(업종 이름이 바뀐 적이 있어 이름 일부로 찾음 — 못 찾은 이름은 「❌ 목록에 없음」으로 출력)
"""
import csv
import os
import time
from datetime import datetime, timedelta, timezone

from pykrx import stock

KST = timezone(timedelta(hours=9))
END = datetime.now(KST).strftime("%Y%m%d")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_tmp_sector.csv")

# (열 이름, 지수 이름에 들어가는 글자 후보 — 앞쪽 먼저)
WANT = [
    ("food", ["음식료"]),
    ("chem", ["화학"]),
    ("steel", ["철강"]),
    ("mach", ["기계"]),
    ("elec", ["전기전자", "전기·전자"]),
    ("auto", ["운수장비", "운송장비"]),
    ("util", ["전기가스", "전기·가스"]),
    ("trans", ["운수창고", "운송·창고"]),
    ("bank", ["은행"]),
    ("fin", ["금융"]),
    ("constr", ["건설"]),
    ("pharm", ["의약품", "제약"]),
]


def index_list():
    """오늘 기준 코스피 지수 코드·이름 목록."""
    out = []
    for code in stock.get_index_ticker_list(market="KOSPI"):
        try:
            out.append((code, stock.get_index_ticker_name(code)))
        except Exception:
            pass
    return out


def history(code):
    data = {}
    for y in range(1980, int(END[:4]) + 1, 5):
        s, e = f"{y}0101", min(f"{y + 4}1231", END)
        df = None
        for _ in range(3):
            try:
                df = stock.get_index_ohlcv(s, e, code)
                break
            except Exception as ex:
                print(f"    재시도 {code} {s}: {ex}")
                time.sleep(3)
        if df is not None:
            for d, row in df.iterrows():
                c = float(row["종가"])
                if c > 0:
                    data[d.strftime("%Y-%m-%d")] = c
        time.sleep(0.5)
    return data


def main():
    lst = index_list()
    print(f"코스피 지수 {len(lst)}개:")
    for code, name in lst:
        print(f"  {code} {name}")
    cols = {}
    for col, keys in WANT:
        hit = None
        for k in keys:
            hit = next(((c, n) for c, n in lst if k in n), None)
            if hit:
                break
        if not hit:
            print(f"  ❌ {col}: 목록에 없음 ({keys})")
            continue
        v = history(hit[0])
        cols[f"{col}_{hit[0]}"] = v
        print(f"  {col:6} {hit[0]} {hit[1]}: {len(v)}일 ({min(v) if v else '-'} ~ {max(v) if v else '-'})")
    if not cols:
        print("받은 업종이 없음 — 저장 안 함")
        return
    days = sorted(set().union(*[set(v) for v in cols.values()]))
    names = list(cols)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + names)
        for d in days:
            w.writerow([d] + [cols[n].get(d, "") for n in names])
    print(f"\n저장: {OUT} ({len(days)}줄, {os.path.getsize(OUT) // 1024}KB)")


if __name__ == "__main__":
    main()
