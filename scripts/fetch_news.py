"""
뉴스 RSS 수집 → data/news.json
GitHub Actions에서 2시간마다 자동 실행
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
# 이데일리(봇차단), 전자신문(봇차단), 한경 industry(경로없음), 연합IT(경로폐지) 제거
# 대체: 조선비즈, 서울경제, 한경IT(기존OK) 등 활용
FEEDS = {
    "breaking": [
        {"name": "연합뉴스", "url": "https://www.yna.co.kr/rss/news.xml"},
        {"name": "한국경제", "url": "https://www.hankyung.com/feed/all-news"},
        {"name": "매일경제", "url": "https://www.mk.co.kr/rss/30000001/"},
        {"name": "파이낸셜뉴스", "url": "https://www.fnnews.com/rss/r20/fn_realnews_all.xml"},
        {"name": "SBS", "url": "https://news.sbs.co.kr/news/headlineRssFeed.do?plink=RSSREADER"},
    ],
    "economy": [
        {"name": "한국경제", "url": "https://www.hankyung.com/feed/economy"},
        {"name": "매일경제", "url": "https://www.mk.co.kr/rss/30100041/"},
        {"name": "파이낸셜뉴스", "url": "https://www.fnnews.com/rss/r20/fn_realnews_economy.xml"},
        {"name": "연합뉴스 경제", "url": "https://www.yna.co.kr/rss/economy.xml"},
        {"name": "SBS 경제", "url": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=02&plink=RSSREADER"},
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
        {"name": "한국경제 IT", "url": "https://www.hankyung.com/feed/it"},
        {"name": "연합뉴스 과학", "url": "https://www.yna.co.kr/rss/science.xml"},
        {"name": "매일경제 IT", "url": "https://www.mk.co.kr/rss/50600019/"},
    ],
    "industry": [
        {"name": "매일경제 산업", "url": "https://www.mk.co.kr/rss/30200030/"},
        {"name": "파이낸셜뉴스 산업", "url": "https://www.fnnews.com/rss/r20/fn_realnews_industry.xml"},
        {"name": "한국경제 사회", "url": "https://www.hankyung.com/feed/society"},
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def parse_rss(xml_text, source_name):
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")

        title = (title_el.text or "").strip() if title_el is not None else ""
        link = (link_el.text or "").strip() if link_el is not None else ""
        pub_date = (pub_el.text or "").strip() if pub_el is not None else ""

        if not title or not link:
            continue

        iso = ""
        if pub_date:
            try:
                iso = parsedate_to_datetime(pub_date).isoformat()
            except:
                iso = pub_date

        items.append({"title": title, "link": link, "pubDate": iso, "source": source_name})

    return items


def fetch_feed(feed):
    try:
        r = requests.get(feed["url"], headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        items = parse_rss(r.text, feed["name"])
        return items, None
    except Exception as e:
        return [], str(e)


def dedupe(items, max_items=80):
    seen = set()
    unique = []
    for it in items:
        key = it["title"].replace(" ", "").lower()[:40]
        if key not in seen:
            seen.add(key)
            unique.append(it)
    unique.sort(key=lambda x: x.get("pubDate", ""), reverse=True)
    return unique[:max_items]


def main():
    now = datetime.now(KST)
    result = {"updated": now.strftime("%Y-%m-%d %H:%M KST"), "categories": {}}
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
