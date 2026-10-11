"""
뉴스 텔레그램 알림 + 일별 JSON 아카이브 (NAVER API HUB 버전)
오라클 VM crontab:
  07:30 KST — 증권/해외증시 (채널+DM)
  12:00 KST — 부동산/하남감북 (DM만)

사용법:
  python3 news_alert.py                     # 전체 카테고리
  python3 news_alert.py --cats 증권 해외증시  # 지정 카테고리만
  python3 news_alert.py --cats 부동산 "하남 감북"

환경변수:
  NAVER_CLIENT_ID      — 네이버 클라우드 NAVER API HUB Client ID
  NAVER_CLIENT_SECRET  — 네이버 클라우드 NAVER API HUB Client Secret
  TELEGRAM_BOT_TOKEN   — 텔레그램 봇 토큰
  TELEGRAM_CHAT_ID     — 텔레그램 채팅 ID
"""
import requests
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
TOP_N = 10

# 네이버 API HUB
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
NAVER_API_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

# 텔레그램
from telegram_helper import send_all as _send_all, send_dm as _send_dm

# 채널 발송 제외 카테고리 (봇 DM만 발송)
DM_ONLY_CATS = {"부동산", "하남 감북"}

# 경로
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ARCHIVE_DIR = REPO_ROOT / "data" / "news_archive"

# 카테고리별 검색어
CATEGORIES = {
    "부동산": ["부동산", "아파트 분양", "재건축 재개발"],
    "증권": ["증권 주식", "코스피 코스닥", "공매도 기관 외국인"],
    "해외증시": ["미국 증시", "나스닥 S&P500", "뉴욕 증시 마감"],
    "하남 감북": ["하남 감북동 그린벨트", "하남 그린벨트 해제", "하남 감북 개발", "하남 감북지구", "하남 개발제한구역 해제"],
}

HEADERS = {
    "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
    "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET,
}


def clean_html(text):
    """HTML 태그·엔티티 제거"""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&quot;", '"').replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&apos;", "'")
    return text.strip()


def search_news(query, display=15):
    """네이버 API HUB 뉴스 검색"""
    params = {
        "query": query,
        "display": display,
        "start": 1,
        "sort": "date",
    }
    try:
        r = requests.get(NAVER_API_URL, headers=HEADERS, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        items = []
        for it in data.get("items", []):
            title = clean_html(it.get("title", ""))
            link = it.get("link", "") or it.get("originallink", "")
            pub = it.get("pubDate", "")
            if title and link:
                items.append({
                    "title": title,
                    "link": link,
                    "pubDate": pub,
                    "source": extract_source(it.get("originallink", link)),
                })
        return items, None
    except Exception as e:
        return [], str(e)[:100]


def extract_source(url):
    """URL에서 언론사명 추출"""
    domain_map = {
        "hankyung.com": "한국경제",
        "mk.co.kr": "매일경제",
        "yna.co.kr": "연합뉴스",
        "fnnews.com": "파이낸셜뉴스",
        "chosun.com": "조선일보",
        "donga.com": "동아일보",
        "joongang.co.kr": "중앙일보",
        "hani.co.kr": "한겨레",
        "khan.co.kr": "경향신문",
        "sedaily.com": "서울경제",
        "edaily.co.kr": "이데일리",
        "mt.co.kr": "머니투데이",
        "newsis.com": "뉴시스",
        "news1.kr": "뉴스1",
        "ytn.co.kr": "YTN",
        "sbs.co.kr": "SBS",
        "kbs.co.kr": "KBS",
        "mbc.co.kr": "MBC",
        "asiae.co.kr": "아시아경제",
        "biz.heraldcorp.com": "헤럴드경제",
        "heraldcorp.com": "헤럴드경제",
        "nocutnews.co.kr": "노컷뉴스",
        "hankookilbo.com": "한국일보",
    }
    for domain, name in domain_map.items():
        if domain in url:
            return name
    return ""


def filter_recent(items, hours=24):
    """pubDate 기준 N시간 이내 기사만 남김."""
    from email.utils import parsedate_to_datetime
    cutoff = datetime.now(KST) - timedelta(hours=hours)
    recent = []
    for it in items:
        try:
            pub = parsedate_to_datetime(it["pubDate"])
            if pub >= cutoff:
                recent.append(it)
        except Exception:
            pass  # 파싱 실패한 기사는 버림
    return recent


def dedupe_top(all_items, n=TOP_N):
    """중복 제거 + 최신순 상위 N개"""
    seen = set()
    unique = []
    for it in all_items:
        key = it["title"].replace(" ", "").lower()[:40]
        if key not in seen:
            seen.add(key)
            unique.append(it)
    unique.sort(key=lambda x: x.get("pubDate", ""), reverse=True)
    return unique[:n]


def send_telegram(text, category=""):
    if category in DM_ONLY_CATS:
        return _send_dm(text)
    return _send_all(text)


def format_telegram(category, items):
    now = datetime.now(KST)
    lines = [f"📰 <b>{category} 뉴스 Top {len(items)}</b>  ({now.strftime('%m/%d %H:%M')})"]
    lines.append("")
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {it['title']}")
        lines.append(it["link"])
        lines.append("")
    return "\n".join(lines)


def parse_cats():
    """--cats 뒤의 카테고리명 파싱. 없으면 전체."""
    args = sys.argv[1:]
    if '--cats' not in args:
        return list(CATEGORIES.keys())
    idx = args.index('--cats')
    cats = args[idx+1:]
    valid = [c for c in cats if c in CATEGORIES]
    if not valid:
        print(f"⚠️ 유효한 카테고리 없음: {cats}")
        print(f"   사용 가능: {list(CATEGORIES.keys())}")
        sys.exit(1)
    return valid


def main():
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    run_cats = parse_cats()
    print(f"뉴스 알림 시작: {now.strftime('%Y-%m-%d %H:%M')} — {run_cats}")

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("❌ NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수 없음")
        return

    # 기존 아카이브 로드 (하루 2회 실행 시 머지)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"{today}.json"
    if archive_path.exists():
        with open(archive_path, "r", encoding="utf-8") as f:
            archive = json.load(f)
    else:
        archive = {"date": today, "categories": {}}
    archive["updated"] = now.strftime("%Y-%m-%d %H:%M KST")

    for cat in run_cats:
        queries = CATEGORIES[cat]
        all_items = []
        errors = []

        for q in queries:
            items, err = search_news(q, display=15)
            if err:
                errors.append(f"{q}: {err}")
            else:
                all_items.extend(items)
            time.sleep(0.3)

        all_items = filter_recent(all_items, hours=24)
        top = dedupe_top(all_items, TOP_N)
        archive["categories"][cat] = {"items": top, "count": len(top)}

        if top:
            msg = format_telegram(cat, top)
            ok = send_telegram(msg, category=cat)
            dest = "DM만" if cat in DM_ONLY_CATS else "DM+채널"
            print(f"  {cat}: {len(top)}개 → 텔레그램 {dest} {'✅' if ok else '❌'}")
        else:
            print(f"  {cat}: 0개 (24시간 이내 뉴스 없음)")
            if cat == "하남 감북":
                now_str = datetime.now(KST).strftime('%m/%d %H:%M')
                send_telegram(f"📰 <b>{cat} 뉴스</b>  ({now_str})\n\n오늘 관련 뉴스 없음", category=cat)

        time.sleep(1)

    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=1)
    print(f"✅ 아카이브 저장: {archive_path}")


if __name__ == "__main__":
    main()
