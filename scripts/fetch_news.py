"""
뉴스 RSS 수집 -> data/news.json
GitHub Actions 2시간마다 자동 실행
"""
import requests
import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
OUTPUT = "data/news.json"
TIMEOUT = 15
MAX_RETRY = 2
RETRY_DELAY = 3

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
        {"name": "매일경제 IT", "url": "https://www.mk.co.kr/rss/50600019/"},
        {"name": "연합뉴스", "url": "https://www.yna.co.kr/rss/news.xml"},
        {"name": "SBS", "url": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=08&plink=RSSREADER"},
    ],
    "industry": [
        {"name": "매일경제 산업", "url": "https://www.mk.co.kr/rss/30200030/"},
        {"name": "파이낸셜뉴스 산업", "url": "https://www.fnnews.com/rss/r20/fn_realnews_industry.xml"},
        {"name": "연합뉴스 경제", "url": "https://www.yna.co.kr/rss/economy.xml"},
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def parse_rss(xml_text, source_name):
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    for item in root.iter("item"):
        t = item.find("title")
        l = item.find("link")
        p = item.find("pubDate")
        title = (t.text or "").strip() if t is not None else ""
        link = (l.text or "").strip() if l is not None else ""
        pub = (p.text or "").strip() if p is not None else ""
        if not title or not link:
            continue
        iso = ""
        if pub:
            try:
                iso = parsedate_to_datetime(pub).isoformat()
            except:
                iso = pub
        items.append({"title": title, "link": link, "pubDate": iso, "source": source_name})
    return items


def fetch_feed(feed):
    """재시도 포함 피드 수집"""
    last_err = ""
    for attempt in range(MAX_RETRY):
        try:
            r = requests.get(feed["url"], headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            items = parse_rss(r.text, feed["name"])
            if items:
                return items, None
            last_err = "파싱 결과 0건"
        except requests.exceptions.HTTPError as e:
            last_err = f"HTTP {r.status_code}"
            if r.status_code == 403:
                break  # 403은 재시도 무의미
        except Exception as e:
            last_err = str(e)[:80]
        if attempt < MAX_RETRY - 1:
            time.sleep(RETRY_DELAY)
    return [], last_err


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
            else:
                all_items.extend(items)
                successes.append(feed["name"])
                total_ok += 1

        unique = dedupe(all_items)
        result["categories"][cat] = {
            "items": unique,
            "count": len(unique),
            "sources_ok": successes,
            "sources_fail": [e.split(":")[0] for e in errors],
        }
        status = f"  {cat}: {len(unique)}개 (성공 {len(successes)}/{len(feeds)})"
        if errors:
            status += f" — 실패: {', '.join(errors)}"
        print(status)

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    # ── 날짜별 아카이브 저장 ──
    archive_dir = os.path.join("data", "news")
    os.makedirs(archive_dir, exist_ok=True)
    today_str = now.strftime("%Y-%m-%d")
    archive_file = os.path.join(archive_dir, f"{today_str}.json")

    # 기존 아카이브가 있으면 기사 머지 (중복 제거)
    existing = {}
    if os.path.exists(archive_file):
        try:
            with open(archive_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except:
            existing = {}

    merged = {"date": today_str, "updated": result["updated"], "categories": {}}
    for cat in result["categories"]:
        new_items = result["categories"][cat]["items"]
        old_items = existing.get("categories", {}).get(cat, {}).get("items", [])
        # 합치고 중복 제거
        all_items = new_items + old_items
        seen = set()
        unique = []
        for it in all_items:
            key = it["title"].replace(" ", "").lower()[:40]
            if key not in seen:
                seen.add(key)
                unique.append(it)
        unique.sort(key=lambda x: x.get("pubDate", ""), reverse=True)
        merged["categories"][cat] = {
            "items": unique[:200],  # 하루 최대 200개
            "count": min(len(unique), 200),
        }

    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)

    # ── 아카이브 인덱스 갱신 ──
    import glob
    archive_files = glob.glob(os.path.join(archive_dir, "20??-??-??.json"))
    dates = sorted(
        [os.path.splitext(os.path.basename(f))[0] for f in archive_files],
        reverse=True
    )
    # 90일 넘으면 오래된 것 삭제
    if len(dates) > 90:
        for old_d in dates[90:]:
            old_f = os.path.join(archive_dir, f"{old_d}.json")
            if os.path.exists(old_f):
                os.remove(old_f)
        dates = dates[:90]

    index = {"dates": dates, "latest": dates[0] if dates else None}
    with open(os.path.join(archive_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    print(f"\n✅ 완료: {now.strftime('%Y-%m-%d %H:%M')} — 성공 {total_ok}, 실패 {total_fail}")
    print(f"   아카이브: {archive_file} ({len(dates)}일치 보관)")


if __name__ == "__main__":
    main()
