"""
스크리너 텔레그램 요약 알림
==========================
매일 20:55 실행 — fetch_screener.py 결과를 읽어서 텔레그램 발송.

환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import os, sys, json, glob
import urllib.request
from datetime import date

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)
SCR_DIR    = os.path.join(ROOT_DIR, 'data', 'kr', 'screener')


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


def main():
    today = date.today().strftime('%Y-%m-%d')
    path = os.path.join(SCR_DIR, f'{today}.json')

    if not os.path.exists(path):
        print(f'  {today} 스크리너 파일 없음 — 알림 생략')
        return

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    signals = data.get('signals', {})
    summary = data.get('summary', {})

    lines = [f'<b>📊 스크리너 요약 — {today}</b>\n']

    # 50일선 돌파
    ma50 = signals.get('ma50_breakout', [])
    if ma50:
        names = ', '.join(s['name'] for s in ma50[:8])
        lines.append(f'🟢 <b>50일선 돌파 ({len(ma50)})</b>\n  {names}')

    # 골든크로스
    gc = signals.get('golden_cross', [])
    if gc:
        names = ', '.join(s['name'] for s in gc[:8])
        lines.append(f'✨ <b>골든크로스 ({len(gc)})</b>\n  {names}')

    # 데드크로스
    dc = signals.get('dead_cross', [])
    if dc:
        names = ', '.join(s['name'] for s in dc[:8])
        lines.append(f'💀 <b>데드크로스 ({len(dc)})</b>\n  {names}')

    # 52주 신고가
    hi = signals.get('new_high_52w', [])
    if hi:
        names = ', '.join(s['name'] for s in hi[:8])
        lines.append(f'🔺 <b>52주 신고가 ({len(hi)})</b>\n  {names}')

    # 52주 신저가
    lo = signals.get('new_low_52w', [])
    if lo:
        names = ', '.join(s['name'] for s in lo[:8])
        lines.append(f'🔻 <b>52주 신저가 ({len(lo)})</b>\n  {names}')

    # RSI 과매도
    rsi_lo = signals.get('rsi_oversold', [])
    if rsi_lo:
        top5 = sorted(rsi_lo, key=lambda x: x.get('rsi', 99))[:5]
        items = ', '.join(f"{s['name']}({s['rsi']:.0f})" for s in top5)
        lines.append(f'📉 <b>RSI 과매도 ({len(rsi_lo)})</b>\n  {items}')

    # 거래량 급등
    vs = signals.get('volume_spike', [])
    if vs:
        top5 = sorted(vs, key=lambda x: -x.get('ratio', 0))[:5]
        items = ', '.join(f"{s['name']}({s['ratio']:.1f}x)" for s in top5)
        lines.append(f'📊 <b>거래량 급등 ({len(vs)})</b>\n  {items}')

    # 외인 순매수 Top5
    fb = signals.get('foreign_top15_buy', [])
    if fb:
        top5 = fb[:5]
        items = ', '.join(s['name'] for s in top5)
        lines.append(f'🏦 <b>외인 매수 Top5</b>\n  {items}')

    # 외인 순매도 Top5
    fs = signals.get('foreign_top15_sell', [])
    if fs:
        top5 = fs[:5]
        items = ', '.join(s['name'] for s in top5)
        lines.append(f'🏦 <b>외인 매도 Top5</b>\n  {items}')

    # 기관 순매수 Top5
    ib = signals.get('institution_top15_buy', [])
    if ib:
        top5 = ib[:5]
        items = ', '.join(s['name'] for s in top5)
        lines.append(f'🏛 <b>기관 매수 Top5</b>\n  {items}')

    # 프매 흡수
    pab = signals.get('program_absorb_bull', [])
    if pab:
        names = ', '.join(s['name'] for s in pab[:5])
        lines.append(f'🤖 <b>프매 흡수(강세) ({len(pab)})</b>\n  {names}')

    # 수치 요약
    lines.append(f'\n<b>요약</b>: 정배열 {summary.get("aligned_bull",0)} | '
                 f'BB돌파 {summary.get("bb_upper_close",0)}+{summary.get("bb_upper_intra",0)} | '
                 f'MACD골든 {summary.get("macd_golden",0)}')

    msg = '\n'.join(lines)

    # 텔레그램 메시지 4096자 제한
    if len(msg) > 4000:
        msg = msg[:4000] + '\n...(생략)'

    if send_telegram(msg):
        print(f'✅ 텔레그램 발송 완료: {today}')
    else:
        print(f'❌ 텔레그램 발송 실패: {today}')


if __name__ == '__main__':
    main()
