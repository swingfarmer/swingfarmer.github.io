"""
시장 지표 텔레그램 알림
======================
fetch_market_indicators.py 결과 → 텔레그램 발송.
아침(07:30) + 저녁(18:50) 2회 cron.

환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import os, sys, json
import urllib.request
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '')

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)
INDICATORS_FILE = os.path.join(ROOT_DIR, 'data', 'market_indicators.json')
NEWS_FILE = os.path.join(ROOT_DIR, 'data', 'news.json')
RATES_FILE = os.path.join(ROOT_DIR, 'data', 'rates.json')
RATES_HIST_FILE = os.path.join(ROOT_DIR, 'data', 'rates_history.json')
FX_STATE_FILE = os.path.join(SCRIPT_DIR, 'fx_alert_state.json')
NEWS_CATS = ['economy', 'stock', 'breaking']  # 경제, 증시, 속보


def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print('  텔레그램 미설정')
        return False
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    body = json.dumps({
        'chat_id': TELEGRAM_CHAT,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    }).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json',
    })
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f'  텔레그램 전송 실패: {e}')
        return False


def fmt_num(val, decimals=2):
    """숫자 포맷 (천단위 콤마 + 소수점)."""
    if val is None:
        return '-'
    if abs(val) >= 1000:
        return f'{val:,.{decimals}f}'
    return f'{val:.{decimals}f}'


def fmt_change(change_pct):
    """변동률 포맷 (▲/▼ + 색상 없이 텍스트)."""
    if change_pct is None or change_pct == 0:
        return '→ 0.00%'
    arrow = '▲' if change_pct > 0 else '▼'
    return f'{arrow} {abs(change_pct):.2f}%'


def get_fx_change(current_val, key='USD_KRW'):
    """rates_history.json에서 전일 대비 변동률·변동액 반환. key: 히스토리 필드명."""
    if not os.path.exists(RATES_HIST_FILE):
        return None
    try:
        with open(RATES_HIST_FILE, 'r') as f:
            hist = json.load(f)
        # 구조: 리스트 [...] 또는 {"history": [...]}
        entries = hist if isinstance(hist, list) else hist.get('history', [])
        if len(entries) < 2:
            return None
        prev = entries[-2]
        # 키 구조: 플랫(prev['USD_KRW']) 또는 중첩(prev['rates']['USD_KRW'])
        prev_val = prev.get(key) or prev.get('rates', {}).get(key)
        if not prev_val or prev_val == 0:
            return None
        chg_pct = (current_val - prev_val) / prev_val * 100
        chg_amt = current_val - prev_val
        return (round(chg_pct, 2), round(chg_amt, 2))
    except:
        return None


def check_fx_band(current_usd):
    """50원 구간 돌파 체크 → 알림 메시지 or None."""
    state = {}
    if os.path.exists(FX_STATE_FILE):
        try:
            with open(FX_STATE_FILE, 'r') as f:
                state = json.load(f)
        except:
            pass

    band = int(current_usd // 50)
    prev_band = state.get('last_band')
    msg = None

    if prev_band is not None and band != prev_band:
        band_low = band * 50
        band_high = band_low + 50
        direction = '📈 상승' if band > prev_band else '📉 하락'
        msg = (f'<b>💱 환율 구간 변동</b>\n'
               f'  {direction} → {current_usd:,.2f}원\n'
               f'  새 구간: {band_low:,}~{band_high:,}원')

    state['last_band'] = band
    with open(FX_STATE_FILE, 'w') as f:
        json.dump(state, f)

    return msg


def build_message(data, news_items=None):
    """market_indicators.json + news → 텔레그램 메시지 생성."""
    if news_items is None:
        news_items = []
    now = datetime.now(KST)
    hour = now.hour
    session = '🌅 아침' if hour < 12 else '🌙 저녁'

    lines = [f'<b>{session} 시장 브리핑 — {now.strftime("%m/%d %H:%M")}</b>\n']

    indicators = {ind['ticker']: ind for ind in data.get('indicators', [])}
    rates = data.get('rates', {})

    # ── 한국 지수 ──
    kr_tickers = ['^KS11', '^KQ11']
    kr_items = [indicators[t] for t in kr_tickers if t in indicators]
    if kr_items:
        lines.append('<b>🇰🇷 한국</b>')
        for ind in kr_items:
            lines.append(f"  {ind['name']}: {fmt_num(ind['price'], 2)} {fmt_change(ind['change_pct'])}")

    # ── 미국 지수 ──
    us_tickers = ['^GSPC', '^IXIC', '^DJI']
    us_items = [indicators[t] for t in us_tickers if t in indicators]
    if us_items:
        lines.append('<b>🇺🇸 미국</b>')
        for ind in us_items:
            lines.append(f"  {ind['name']}: {fmt_num(ind['price'], 2)} {fmt_change(ind['change_pct'])}")

    # ── VIX ──
    if '^VIX' in indicators:
        vix = indicators['^VIX']
        level = ''
        v = vix['price']
        if v < 15:
            level = '(안정)'
        elif v < 20:
            level = '(보통)'
        elif v < 30:
            level = '(경계)'
        else:
            level = '(공포)'
        lines.append(f'<b>😱 VIX</b>: {fmt_num(v, 2)} {fmt_change(vix["change_pct"])} {level}')

    # ── 환율 ──
    if rates.get('USD_KRW'):
        lines.append('<b>💱 환율</b>')
        fx_items = [
            ('원/달러', 'USD_KRW', 2),
            ('원/엔(100)', 'JPY100_KRW', 2),
            ('원/위안', 'CNY_KRW', 2),
        ]
        for label, key, dec in fx_items:
            val = rates.get(key)
            if not val:
                continue
            fx_line = f"  {label}: {fmt_num(val, dec)}"
            chg = get_fx_change(val, key)
            if chg:
                chg_pct, chg_amt = chg
                arrow = '▲' if chg_pct > 0 else '▼'
                warn = ' ⚠️' if abs(chg_pct) >= 1 else ''
                fx_line += f" {arrow}{abs(chg_pct):.2f}% ({chg_amt:+.2f}){warn}"
            lines.append(fx_line)

    # ── 금리 ──
    rate_tickers = ['^IRX', '^FVX', '^TNX', '^TYX']
    rate_items = [indicators[t] for t in rate_tickers if t in indicators]
    if rate_items:
        lines.append('<b>📊 미국 금리</b>')
        for ind in rate_items:
            lines.append(f"  {ind['name']}: {fmt_num(ind['price'], 3)}% {fmt_change(ind['change_pct'])}")

        # 장단기 스프레드 (10yr - IRX 또는 10yr 단독)
        tnx = indicators.get('^TNX')
        irx = indicators.get('^IRX')
        if tnx and irx:
            spread = round(tnx['price'] - irx['price'], 3)
            inv = ' ⚠역전' if spread < 0 else ''
            lines.append(f"  10yr-13w 스프레드: {spread:+.3f}%p{inv}")

    # ── 원유 ──
    if 'CL=F' in indicators:
        oil = indicators['CL=F']
        lines.append(f"<b>🛢️ WTI</b>: ${fmt_num(oil['price'], 2)} {fmt_change(oil['change_pct'])}")

    # ── 금시세 ──
    if rates.get('GOLD_KRW_G'):
        gold = rates['GOLD_KRW_G']
        gold_line = f"<b>🥇 금</b>: {fmt_num(gold, 0)}원/g"
        chg = get_fx_change(gold, 'GOLD_KRW_G')
        if chg:
            chg_pct, chg_amt = chg
            arrow = '▲' if chg_pct > 0 else '▼'
            gold_line += f" {arrow}{abs(chg_pct):.2f}% ({chg_amt:+,.0f})"
        lines.append(gold_line)

    # ── 뉴스 헤드라인 ──
    if news_items:
        lines.append('\n<b>📰 주요 뉴스</b>')
        for item in news_items[:5]:
            lines.append(f"  · {item['title']}")

    # 업데이트 시각
    lines.append(f"\n<i>데이터: {data.get('updated', '-')}</i>")

    return '\n'.join(lines)


def load_news():
    """news.json에서 경제/증시/속보 헤드라인 추출."""
    if not os.path.exists(NEWS_FILE):
        return []
    try:
        with open(NEWS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        items = []
        cats = data.get('categories', {})
        for cat in NEWS_CATS:
            cat_data = cats.get(cat, {})
            cat_items = cat_data.get('items', [])
            for item in cat_items[:3]:
                items.append({
                    'title': item.get('title', ''),
                    'cat': cat,
                    'pubDate': item.get('pubDate', ''),
                })
        # 최신순 정렬
        items.sort(key=lambda x: x.get('pubDate', ''), reverse=True)
        return items[:5]
    except Exception as e:
        print(f'  뉴스 로드 실패: {e}')
        return []


def main():
    if not os.path.exists(INDICATORS_FILE):
        print(f'❌ {INDICATORS_FILE} 없음 — fetch_market_indicators.py 먼저 실행')
        sys.exit(1)

    with open(INDICATORS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # ── 환율 50원 구간 돌파 체크 ──
    usd_krw = data.get('rates', {}).get('USD_KRW')
    if usd_krw:
        fx_msg = check_fx_band(usd_krw)
        if fx_msg:
            print(f'🔔 {fx_msg}')
            send_telegram(fx_msg)

    # ── 정기 브리핑 ──
    news = load_news()
    msg = build_message(data, news)
    print(msg.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', ''))
    print(f'\n메시지 길이: {len(msg)}자')

    if send_telegram(msg):
        print('✅ 텔레그램 발송 완료')
    else:
        print('❌ 텔레그램 발송 실패')


if __name__ == '__main__':
    main()
