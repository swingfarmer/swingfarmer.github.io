"""
뉴스 텔레그램 알림 + 일별 JSON 아카이브 (NAVER API HUB 버전)
오라클 VM crontab: 매일 07:00 KST
부동산/증권 각 10개 헤드라인 → 텔레그램 발송 + data/news_archive/YYYY-MM-DD.json 저장

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
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 경로
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ARCHIVE_DIR = REPO_ROOT / "data" / "news_archive"

# 카테고리별 검색어
CATEGORIES = {
    "부동산": ["부동산", "아파트 분양", "재건축 재개발"],
    "증권": ["증권 주식", "코스피 코스닥", "공매도 기관 외국인"],
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
            # 네이버 뉴스 링크 우선 (link), 없으면 원본 (originallink)
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


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ 텔레그램 설정 없음, 스킵")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return True
        print(f"⚠️ 텔레그램 {r.status_code}: {r.text[:100]}")
        return False
    except Exception as e:
        print(f"⚠️ 텔레그램 에러: {e}")
        return False


def format_telegram(category, items):
    now = datetime.now(KST)
    lines = [f"📰 <b>{category} 뉴스 Top {len(items)}</b>  ({now.strftime('%m/%d %H:%M')})"]
    lines.append("")
    for i, it in enumerate(items, 1):
        source_tag = f"  — {it['source']}" if it["source"] else ""
        lines.append(f'{i}. <a href="{it["link"]}">{it["title"]}</a>{source_tag}')
    return "\n".join(lines)


def main():
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    print(f"뉴스 알림 시작: {now.strftime('%Y-%m-%d %H:%M')}")

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("❌ NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수 없음")
        return

    archive = {"date": today, "updated": now.strftime("%Y-%m-%d %H:%M KST"), "categories": {}}

    for cat, queries in CATEGORIES.items():
        all_items = []
        errors = []

        for q in queries:
            items, err = search_news(q, display=15)
            if err:
                errors.append(f"{q}: {err}")
            else:
                all_items.extend(items)
            time.sleep(0.3)

        top = dedupe_top(all_items, TOP_N)
        archive["categories"][cat] = {"items": top, "count": len(top)}

        if top:
            msg = format_telegram(cat, top)
            ok = send_telegram(msg)
            print(f"  {cat}: {len(top)}개 → 텔레그램 {'✅' if ok else '❌'}")
        else:
            print(f"  {cat}: 0개 (에러: {', '.join(errors)})")

        time.sleep(1)

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"{today}.json"
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=1)
    print(f"✅ 아카이브 저장: {archive_path}")


if __name__ == "__main__":
    main()
