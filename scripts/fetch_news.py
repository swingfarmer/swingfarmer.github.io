"""
뉴스 RSS 수집 → data/news.json
GitHub Actions에서 2시간마다 자동 실행
CORS 프록시 의존 제거 — 서버사이드에서 직접 수집
"""
import requests
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
OUTPUT = "data/news.json"
TIMEOUT = 15

# ── 카테고리별 RSS 소스 ──
FEEDS = {
    "breaking": [
        {"name": "연합뉴스", "url": "https://www.yna.co.kr/rss/news.xml"},
        {"name": "한국경제", "url": "https://www.hankyung.com/feed/all-news"},
        {"name": "매일경제", "url": "https://www.mk.co.kr/rss/30000001/"},
        {"name": "파이낸셜뉴스", "url": "https://www.fnnews.com/rss/r20/fn_realnews_all.xml"},
        {"name": "SBS", "url": "https://news.sbs.co.kr/news/headlineRssFeed.do?plink=RSSREADER"},
        {"name": "이데일리", "url": "https://rss.edaily.co.kr/edaily_news.xml"},
    ],
    "economy": [
        {"name": "한국경제", "url": "https://www.hankyung.com/feed/economy"},
        {"name": "매일경제", "url": "https://www.mk.co.kr/rss/30100041/"},
        {"name": "파이낸셜뉴스", "url": "https://www.fnnews.com/rss/r20/fn_realnews_economy.xml"},
        {"name": "연합뉴스 경제", "url": "https://www.yna.co.kr/rss/economy.xml"},
        {"name": "SBS 경제", "url": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=02&plink=RSSREADER"},
        {"name": "이데일리 경제", "url": "https://rss.edaily.co.kr/economy_news.xml"},
    ],
    "realestate": [
        {"name": "한국경제", "url": "https://www.hankyung.com/feed/realestate"},
        {"name": "매일경제", "url": "https://www.mk.co.kr/rss/50300009/"},
        {"name": "연합뉴스 경제", "url": "https://www.yna.co.kr/rss/economy.xml"},
    ],
    "stock": [
        {"name": "한국경제 증권", "url": "https://www.hankyung.com/feed/finance"},
        {"name": "매일경제 증권", "url": "https://www.mk.co.kr/rss/50200011/"},
        {"name": "파이낸셜뉴스", "url": "https://www.fnnews.com/rss/r20/fn_realnews_stock.xml"},
        {"name": "연합뉴스 경제", "url": "https://www.yna.co.kr/rss/economy.xml"},
        {"name": "이데일리 증권", "url": "https://rss.edaily.co.kr/stock_news.xml"},
    ],
    "international": [
        {"name": "연합뉴스 국제", "url": "https://www.yna.co.kr/rss/international.xml"},
        {"name": "한국경제 국제", "url": "https://www.hankyung.com/feed/international"},
        {"name": "SBS 국제", "url": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=07&plink=RSSREADER"},
    ],
    "politics": [
        {"name": "연합뉴스 정치", "url": "https://www.yna.co.kr/rss/politics.xml"},
        {"name": "한국경제 정치", "url": "https://www.hankyung.com/feed/politics"},
        {"name": "SBS 정치", "url": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=01&plink=RSSREADER"},
    ],
    "tech": [
        {"name": "전자신문", "url": "https://rss.etnews.com/Section901.xml"},
        {"name": "한국경제 IT", "url": "https://www.hankyung.com/feed/it"},
        {"name": "연합뉴스 IT", "url": "https://www.yna.co.kr/rss/it.xml"},
    ],
    "industry": [
        {"name": "한국경제 산업", "url": "https://www.hankyung.com/feed/industry"},
        {"name": "매일경제 산업", "url": "https://www.mk.co.kr/rss/30200030/"},
        {"name": "파이낸셜뉴스 산업", "url": "https://www.fnnews.com/rss/r20/fn_realnews_industry.xml"},
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SwingFarmerBot/1.0; +https://swingfarmer.github.io)"
}


def parse_rss(xml_text, source_name):
    """RSS XML → 기사 리스트"""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    # RSS 2.0 or Atom
    for item in root.iter("item"):
        title = ""
        link = ""
        pub_date = ""

        t = item.find("title")
        if t is not None and t.text:
            title = t.text.strip()

        l = item.find("link")
        if l is not None and l.text:
            link = l.text.strip()

        p = item.find("pubDate")
        if p is not None and p.text:
            pub_date = p.text.strip()

        if title and link:
            # ISO 변환 시도
            iso = ""
            if pub_date:
                try:
                    dt = parsedate_to_datetime(pub_date)
                    iso = dt.isoformat()
                except:
                    iso = pub_date

            items.append({
                "title": title,
                "link": link,
                "pubDate": iso,
                "source": source_name
            })

    return items


def fetch_feed(feed):
    """단일 피드 수집"""
    try:
        r = requests.get(feed["url"], headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        # 인코딩 처리
        r.encoding = r.apparent_encoding or "utf-8"
        items = parse_rss(r.text, feed["name"])
        return items, None
    except Exception as e:
        return [], str(e)


def dedupe(items, max_items=80):
    """제목 기준 중복 제거 + 최신순 정렬"""
    seen = set()
    unique = []
    for it in items:
        key = it["title"].replace(" ", "").lower()[:40]
        if key not in seen:
            seen.add(key)
            unique.append(it)

    # 날짜 정렬 (최신 먼저)
    unique.sort(key=lambda x: x.get("pubDate", ""), reverse=True)
    return unique[:max_items]


def main():
    now = datetime.now(KST)
    result = {
        "updated": now.strftime("%Y-%m-%d %H:%M KST"),
        "categories": {}
    }

    total_ok = 0
    total_fail = 0

    for cat, feeds in FEEDS.items():
        all_items = []
        errors = []
        successes = []

        for feed in feeds:
            items, err = fetch_feed(feed)
            if err:
                errors.append(f"{feed['name']}: {err}")
                total_fail += 1
            elif len(items) > 0:
                all_items.extend(items)
                successes.append(feed["name"])
                total_ok += 1
            else:
                errors.append(f"{feed['name']}: 기사 0건")
                total_fail += 1

        unique = dedupe(all_items)

        result["categories"][cat] = {
            "items": unique,
            "count": len(unique),
            "sources_ok": successes,
            "sources_fail": [e.split(":")[0] for e in errors],
        }

        status = f"  {cat}: {len(unique)}개 (성공 {len(successes)}/{len(feeds)})"
        if errors:
            status += f" — 실패: {', '.join(e.split(':')[0] for e in errors)}"
        print(status)

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    print(f"\n✅ 완료: {now.strftime('%Y-%m-%d %H:%M')} — 성공 {total_ok}, 실패 {total_fail}")


if __name__ == "__main__":
    main()
