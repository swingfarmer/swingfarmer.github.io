"""
뉴스 텔레그램 알림 + 일별 JSON 아카이브
오라클 VM crontab: 매일 07:00 KST
부동산/증권 각 10개 헤드라인 → 텔레그램 발송 + data/news_archive/YYYY-MM-DD.json 저장
"""
import requests
import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

KST = timezone(timedelta(hours=9))
TIMEOUT = 15
MAX_RETRY = 2
RETRY_DELAY = 3
TOP_N = 10

# 텔레그램
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 스크립트 위치 기준 레포 루트
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ARCHIVE_DIR = REPO_ROOT / "data" / "news_archive"

FEEDS = {
    "부동산": [
        {"name": "한국경제", "url": "https://www.hankyung.com/feed/realestate"},
        {"name": "매일경제", "url": "https://www.mk.co.kr/rss/50300009/"},
        {"name": "연합뉴스 경제", "url": "https://www.yna.co.kr/rss/economy.xml"},
        {"name": "파이낸셜뉴스", "url": "https://www.fnnews.com/rss/r20/fn_realnews_economy.xml"},
    ],
    "증권": [
        {"name": "한국경제 증권", "url": "https://www.hankyung.com/feed/finance"},
        {"name": "매일경제 증권", "url": "https://www.mk.co.kr/rss/50200011/"},
        {"name": "파이낸셜뉴스", "url": "https://www.fnnews.com/rss/r20/fn_realnews_stock.xml"},
        {"name": "연합뉴스 경제", "url": "https://www.yna.co.kr/rss/economy.xml"},
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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
            except Exception:
                iso = pub
        items.append({"title": title, "link": link, "pubDate": iso, "source": source_name})
    return items


def fetch_feed(feed):
    last_err = ""
    for attempt in range(MAX_RETRY):
        try:
            r = requests.get(feed["url"], headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            items = parse_rss(r.text, feed["name"])
            if items:
                return items, None
            last_err = "파싱 0건"
        except requests.exceptions.HTTPError:
            last_err = f"HTTP {r.status_code}"
            if r.status_code == 403:
                break
        except Exception as e:
            last_err = str(e)[:80]
        if attempt < MAX_RETRY - 1:
            time.sleep(RETRY_DELAY)
    return [], last_err


def dedupe_top(items, n=TOP_N):
    seen = set()
    unique = []
    for it in items:
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
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
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
        lines.append(f"{i}. <a href=\"{it['link']}\">{it['title']}</a>")
        lines.append(f"   — {it['source']}")
    return "\n".join(lines)


def main():
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    print(f"뉴스 알림 시작: {now.strftime('%Y-%m-%d %H:%M')}")

    archive = {"date": today, "updated": now.strftime("%Y-%m-%d %H:%M KST"), "categories": {}}

    for cat, feeds in FEEDS.items():
        all_items = []
        errors = []
        for feed in feeds:
            items, err = fetch_feed(feed)
            if err:
                errors.append(f"{feed['name']}: {err}")
            else:
                all_items.extend(items)

        top = dedupe_top(all_items, TOP_N)
        archive["categories"][cat] = {"items": top, "count": len(top)}

        if top:
            msg = format_telegram(cat, top)
            ok = send_telegram(msg)
            print(f"  {cat}: {len(top)}개 → 텔레그램 {'✅' if ok else '❌'}")
        else:
            print(f"  {cat}: 0개 (에러: {', '.join(errors)})")

        time.sleep(1)  # 텔레그램 rate limit 방지

    # 일별 JSON 아카이브 저장
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"{today}.json"
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=1)
    print(f"✅ 아카이브 저장: {archive_path}")


if __name__ == "__main__":
    main()
