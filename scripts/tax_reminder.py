#!/usr/bin/env python3
"""세금 납부 알림 텔레그램 봇.
GitHub Actions cron으로 매일 09:00 KST 실행.
D-7, D-3, 당일 알림 발송.
"""
import os
import json
import urllib.request
from datetime import date, timedelta

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# ── 세금 일정 (tax-calendar와 동일) ──
EVENTS = {
    1: [
        (10, '💰 원천세 납부 (전월분)'),
        (10, '🏥 4대보험료 납부 (전월분)'),
        (25, '📋 부가가치세 확정신고 (7~12월분)'),
        (31, '🏠 면세사업자 사업장현황신고'),
        (31, '🚗 자동차세 연납신청 (10% 할인)'),
    ],
    2: [
        (10, '💰 원천세 납부'),
        (10, '🏥 4대보험료 납부'),
        (28, '📋 면세사업자 사업장현황신고 마감'),
    ],
    3: [
        (10, '💰 원천세 납부'),
        (10, '🏥 4대보험료 납부'),
        (31, '🏢 법인세 신고·납부'),
        (31, '🏢 법인 지방소득세 신고·납부'),
    ],
    4: [
        (10, '💰 원천세 납부'),
        (10, '🏥 4대보험료 납부'),
        (25, '📋 부가가치세 예정신고 (법인 1기)'),
    ],
    5: [
        (10, '💰 원천세 납부'),
        (10, '🏥 4대보험료 납부'),
        (31, '💼 종합소득세 신고·납부'),
        (31, '💼 개인 지방소득세 신고·납부'),
    ],
    6: [
        (10, '💰 원천세 납부'),
        (10, '🏥 4대보험료 납부'),
        (30, '🏠 재산세 (건축물) 납부'),
    ],
    7: [
        (10, '💰 원천세 납부'),
        (10, '🏥 4대보험료 납부'),
        (25, '📋 부가가치세 확정신고 (1~6월분)'),
        (31, '🏠 재산세 (주택 1기분) 납부'),
    ],
    8: [
        (10, '💰 원천세 납부'),
        (10, '🏥 4대보험료 납부'),
        (31, '🏢 법인세 중간예납'),
    ],
    9: [
        (10, '💰 원천세 납부'),
        (10, '🏥 4대보험료 납부'),
        (30, '🏠 재산세 (주택 2기분, 토지) 납부'),
    ],
    10: [
        (10, '💰 원천세 납부'),
        (10, '🏥 4대보험료 납부'),
        (25, '📋 부가가치세 예정신고 (법인 2기)'),
    ],
    11: [
        (10, '💰 원천세 납부'),
        (10, '🏥 4대보험료 납부'),
        (30, '💼 종합소득세 중간예납'),
    ],
    12: [
        (10, '💰 원천세 납부'),
        (10, '🏥 4대보험료 납부'),
        (31, '🏠 종합부동산세 납부'),
    ],
}


def send_telegram(text):
    """텔레그램 메시지 발송."""
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    payload = json.dumps({
        'chat_id': CHAT_ID,
        'text': text,
        'parse_mode': 'HTML',
    }).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={
        'Content-Type': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f'❌ 텔레그램 발송 실패: {e}')
        return False


def main():
    if not BOT_TOKEN or not CHAT_ID:
        print('⚠️ TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 미설정')
        return

    today = date.today()
    alerts = []

    # 이번 달 + 다음 달 일정 확인
    for month_offset in range(2):
        check_month = today.month + month_offset
        check_year = today.year
        if check_month > 12:
            check_month -= 12
            check_year += 1

        for day_num, desc in EVENTS.get(check_month, []):
            try:
                event_date = date(check_year, check_month, day_num)
            except ValueError:
                # 2월 29일 등 존재하지 않는 날짜
                continue

            diff = (event_date - today).days

            if diff == 7:
                alerts.append(f'📅 <b>D-7</b> | {event_date.strftime("%m/%d")} {desc}')
            elif diff == 3:
                alerts.append(f'⚠️ <b>D-3</b> | {event_date.strftime("%m/%d")} {desc}')
            elif diff == 0:
                alerts.append(f'🚨 <b>오늘!</b> | {desc}')

    if not alerts:
        print(f'✅ {today} — 알림 없음')
        return

    header = f'🗓️ <b>세금 알림</b> ({today.strftime("%Y.%m.%d")})\n'
    msg = header + '\n'.join(alerts)
    print(msg.replace('<b>', '').replace('</b>', ''))

    if send_telegram(msg):
        print('✅ 텔레그램 발송 완료')
    else:
        print('❌ 텔레그램 발송 실패')


if __name__ == '__main__':
    main()
