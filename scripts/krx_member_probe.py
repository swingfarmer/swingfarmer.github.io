#!/usr/bin/env python3
"""
업종 소속 조회 — 읽기 전용 (112)
================================
KRX 업종 노트(🔒 research/krx-sector-ytd-2026.html) 「확인 필요」용.
ytd_probe.py의 74종목이 실제로 어느 업종지수(코스피·코스닥)에 들어 있는지,
HDC현대산업개발의 지금 종목명이 무엇인지 화면과 ~/krx_member.txt에만 출력. 레포·DB에는 아무것도 안 씀.

  . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/krx_member_probe.py
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from pykrx import stock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ytd_probe import SECTORS  # 같은 74종목 목록

KST = timezone(timedelta(hours=9))
END = sys.argv[1] if len(sys.argv) > 1 else datetime.now(KST).strftime("%Y%m%d")

# 크기·스타일·테마 지수는 업종 소속이 아니라서 결과에서 뺌
SKIP = ("200", "100", "150", "50", "대형", "중형", "소형", "TOP", "우량", "배당", "레버리지",
        "ESG", "벤처", "글로벌", "프리미어", "외국인", "커버드", "고배당", "선물", "변동성",
        "섹터", "KRX")
EXACT_SKIP = ("코스피", "코스닥")   # 종합지수


def deposit(t):
    """pykrx 버전에 따라 인자 순서가 달라서 두 가지로 시도."""
    for args in ((t, END), (END, t)):
        try:
            r = stock.get_index_portfolio_deposit_file(*args)
            if r is not None and len(r):
                return list(r)
        except Exception:
            pass
    return []


def main():
    lines = [f"기준일 {END}"]

    # 종목 이름 → (티커, 시장)
    names = {}
    for mk in ("KOSPI", "KOSDAQ"):
        for t in stock.get_market_ticker_list(END, market=mk):
            names[stock.get_market_ticker_name(t)] = (t, mk)
    lines.append(f"종목 수: {len(names)}")

    # HDC 들어간 종목 이름
    lines.append("HDC 종목: " + ", ".join(f"{n}({t},{m})" for n, (t, m) in names.items() if "HDC" in n.upper()))

    # 업종지수별 구성종목
    member = {}   # 티커 → [지수 이름]
    n_idx = n_empty = 0
    for mk in ("KOSPI", "KOSDAQ"):
        for it in stock.get_index_ticker_list(END, market=mk):
            nm = stock.get_index_ticker_name(it)
            if nm in EXACT_SKIP or any(s in nm for s in SKIP):
                continue
            n_idx += 1
            ts = deposit(it)
            if not ts:
                n_empty += 1
            for t in ts:
                member.setdefault(t, []).append(f"{'P' if mk == 'KOSPI' else 'Q'}:{nm}")
            time.sleep(0.2)
    lines.append(f"업종지수 {n_idx}개 조회, 구성종목 빈 지수 {n_empty}개")
    lines.append("")

    bad = 0
    for sec, stocks in SECTORS.items():
        lines.append(f"[{sec}]")
        for s in stocks:
            hit = names.get(s)
            if not hit:
                lines.append(f"  ❓ {s}: 종목명 못 찾음")
                bad += 1
                continue
            t, mk = hit
            got = member.get(t, [])
            ok = any(sec.replace("·", "") in g.replace("·", "").replace(" ", "") for g in got)
            mark = "✅" if ok else "⚠"
            if not ok:
                bad += 1
            lines.append(f"  {mark} {s}({t},{mk}): {', '.join(got) or '업종지수에 없음'}")
    lines.append("")
    lines.append(f"⚠·❓ {bad}개")

    out = "\n".join(lines)
    print(out)
    with open(os.path.expanduser("~/krx_member.txt"), "w", encoding="utf-8") as f:
        f.write(out + "\n")
    print("\n저장: ~/krx_member.txt")


if __name__ == "__main__":
    main()
