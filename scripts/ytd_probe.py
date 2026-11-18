#!/usr/bin/env python3
"""
연초 대비(YTD) 조회 — 읽기 전용 (111)
=====================================
KRX 9개 업종 파일(시총 1조 이상 종목)의 2026 연초 대비 등락률을 코스피·코스닥·업종지수와 비교.
화면 출력 + ~/ytd_probe.txt 저장. 레포·DB에는 아무것도 안 씀.

  . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/ytd_probe.py

기준: 2025 마지막 거래일 종가 → 최근 거래일 종가 (수정주가).
양봉 = 최근 종가 > 2026 첫 거래일 시가. 고점대비 = 2026 장중 최고가 대비.
"""
import os
import time
from datetime import datetime, timedelta, timezone

from pykrx import stock

KST = timezone(timedelta(hours=9))
END = datetime.now(KST).strftime("%Y%m%d")
START = "20251215"

SECTORS = {
    "음식료·담배": ["KT&G", "삼양식품", "오리온", "CJ제일제당", "농심", "동원산업", "오뚜기", "롯데웰푸드"],
    "전기전자": ["삼성전자", "SK하이닉스", "LG에너지솔루션", "삼성전기", "삼성SDI", "LG전자", "한미반도체",
              "LG이노텍", "LG디스플레이", "이오테크닉스", "원익IPS"],
    "의료·정밀기기": ["파크시스템스", "티에스이", "클래시스", "케이씨텍", "리브스메드"],
    "유통": ["삼성물산", "포스코인터내셔널", "영원무역", "동서", "ISC", "이마트", "롯데쇼핑", "BGF리테일",
           "신세계", "현대백화점", "GS리테일"],
    "건설": ["현대건설", "대우건설", "한전기술", "GS건설", "DL이앤씨", "IPARK현대산업개발"],   # (112) 옛 이름 HDC현대산업개발(294870)
    "운송·창고": ["HMM", "현대글로비스", "대한항공", "팬오션", "아시아나항공", "CJ대한통운"],
    "통신": ["SK텔레콤", "KT", "LG유플러스"],
    "금융": ["SK스퀘어", "KB금융", "신한지주", "SK", "하나금융지주", "우리금융지주", "메리츠금융지주",
           "HD한국조선해양", "LG", "한진칼", "HD현대", "에코프로", "GS", "한국금융지주", "LS", "JB금융지주",
           "삼성카드", "맥쿼리인프라", "카카오페이", "BNK금융지주"],
    "보험": ["삼성생명", "삼성화재", "DB손해보험", "현대해상", "한화생명"],
}


def stats(df, open_col="시가", hi_col="고가", close_col="종가"):
    """df: 날짜 인덱스. 2025 마지막 종가, 2026 첫 시가, 최근 종가, 2026 최고가."""
    if df is None or df.empty:
        return None
    y25 = df[df.index < "2026-01-01"]
    y26 = df[df.index >= "2026-01-01"]
    if y25.empty or y26.empty:
        return None
    base = float(y25[close_col].iloc[-1])
    op = float(y26[open_col].iloc[0])
    last = float(y26[close_col].iloc[-1])
    hi = float(y26[hi_col].max())
    if not base or not op:
        return None
    return {
        "base": base, "open": op, "last": last, "date": y26.index[-1].strftime("%m/%d"),
        "ytd": (last / base - 1) * 100, "candle": "양봉" if last > op else "음봉",
        "from_hi": (last / hi - 1) * 100,
    }


def fmt(name, s, extra=""):
    if not s:
        return f"{name:<14}  데이터 없음 {extra}"
    return (f"{name:<14} {s['base']:>12,.2f} {s['last']:>12,.2f} {s['ytd']:>+8.1f}% "
            f"{s['candle']}  고점대비 {s['from_hi']:>+6.1f}%  ({s['date']}) {extra}")


def main():
    lines = [f"YTD 조회 {datetime.now(KST):%Y-%m-%d %H:%M} (기준: 2025 마지막 종가 → 최근 종가)", ""]

    # 1) 지수
    lines.append("[지수]  이름 / 2025말 / 최근 / YTD / 연봉 / 2026고점대비")
    idx_names = {}
    for mk in ("KOSPI", "KOSDAQ"):
        for t in stock.get_index_ticker_list(END, market=mk):
            idx_names.setdefault(stock.get_index_ticker_name(t), t)   # 같은 이름이면 코스피 업종 우선
    want = ["코스피", "코스닥"] + list(SECTORS)
    for nm in want:
        t = idx_names.get(nm)
        if not t:
            lines.append(f"{nm:<14}  지수 이름 못 찾음")
            continue
        try:
            df = stock.get_index_ohlcv(START, END, t)
            lines.append(fmt(nm, stats(df), f"[{t}]"))
        except Exception as e:
            lines.append(f"{nm:<14}  에러 {type(e).__name__}: {e}")
        time.sleep(0.2)

    # 2) 종목
    names = {}
    for mk in ("KOSPI", "KOSDAQ"):
        for t in stock.get_market_ticker_list(END, market=mk):
            names.setdefault(stock.get_market_ticker_name(t), (t, mk))
    for sec, lst in SECTORS.items():
        lines.append("")
        lines.append(f"[{sec}]")
        for nm in lst:
            hit = names.get(nm)
            if not hit:
                lines.append(f"{nm:<14}  종목 이름 못 찾음")
                continue
            t, mk = hit
            try:
                df = stock.get_market_ohlcv(START, END, t, adjusted=True)
                lines.append(fmt(nm, stats(df), f"[{t} {mk}]"))
            except Exception as e:
                lines.append(f"{nm:<14}  에러 {type(e).__name__}: {e}")
            time.sleep(0.2)

    out = "\n".join(lines)
    print(out)
    with open(os.path.expanduser("~/ytd_probe.txt"), "w", encoding="utf-8") as f:
        f.write(out + "\n")
    print("\n저장: ~/ytd_probe.txt")


if __name__ == "__main__":
    main()
