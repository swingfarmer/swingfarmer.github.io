#!/usr/bin/env python3
"""
업종지수 시그널 텔레그램 알림
==============================
SECTOR_PRICES에서 26개 업종 시그널 계산 → 호재/악재 요약 발송 (DM만)

cron 예시 (평일 20:20, fetch_sector_prices 이후):
  20 20 * * 1-5 . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/sector_alert.py >> ~/cron.log 2>&1
"""
import os, sys, math
from datetime import datetime

def load_env():
    f = os.path.expanduser('~/.env_secrets')
    if os.path.exists(f):
        for line in open(f):
            line = line.strip()
            if not line or line.startswith('#'): continue
            if line.startswith('export '): line = line[7:]
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
load_env()

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from telegram_helper import send_dm

import oracledb

WALLET_DIR = os.path.expanduser('~/wallet')

SECTOR_NAMES = {
    '0001':'KOSPI','0002':'대형주','0003':'중형주','0004':'소형주',
    '0005':'음식료','0006':'섬유의복','0007':'종이목재','0008':'화학',
    '0009':'의약품','0010':'비금속광물','0011':'철강금속','0012':'기계',
    '0013':'전기전자','0014':'의료정밀','0015':'운수장비','0016':'유통',
    '0017':'전기가스','0018':'건설','0019':'운수창고','0020':'통신',
    '0021':'금융','0024':'증권','0025':'보험','0026':'서비스',
    '0027':'KOSPI200','0028':'제조업',
}

# 업종별 코드만 (지수/규모 제외)
INDUSTRY_CODES = ['0005','0006','0007','0008','0009','0010','0011','0012',
    '0013','0014','0015','0016','0017','0018','0019','0020','0021','0024','0025','0026']


def fetch_data(conn, days=120):
    """SECTOR_PRICES에서 최근 N거래일 데이터 조회"""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT sector_code, trade_date, open_price, high_price, low_price,
               close_price, volume, trade_amount
        FROM SECTOR_PRICES
        WHERE trade_date >= (SELECT MAX(trade_date) - {days} FROM SECTOR_PRICES)
        ORDER BY sector_code, trade_date
    """)
    rows = cur.fetchall()
    cur.close()

    grouped = {}
    for code, dt, o, h, l, c, v, amt in rows:
        if code not in grouped:
            grouped[code] = []
        d = dt.strftime('%Y-%m-%d') if hasattr(dt, 'strftime') else str(dt)
        grouped[code].append({
            'date': d, 'open': float(o), 'high': float(h),
            'low': float(l), 'close': float(c), 'volume': int(v or 0),
            'amount': float(amt or 0)
        })

    return grouped


def ema(values, period):
    """EMA 계산"""
    result = [values[0]]
    k = 2 / (period + 1)
    for i in range(1, len(values)):
        result.append(values[i] * k + result[-1] * (1 - k))
    return result


def compute_signals(code, data):
    """업종 데이터에서 시그널 계산"""
    closes = [d['close'] for d in data]
    amounts = [d['amount'] for d in data]
    n = len(closes)
    if n < 5:
        return None

    latest = closes[-1]
    pct1d = (closes[-1] - closes[-2]) / closes[-2] * 100 if n >= 2 else 0

    # MA
    def calc_ma(p):
        if n < p: return None
        return sum(closes[-p:]) / p

    ma5, ma10, ma20, ma50 = calc_ma(5), calc_ma(10), calc_ma(20), calc_ma(50)
    gap20 = ((latest - ma20) / ma20 * 100) if ma20 else None

    # 배열
    alignment = 'none'
    if all(v is not None for v in [ma5, ma10, ma20, ma50]):
        if latest >= ma5 >= ma10 >= ma20 >= ma50: alignment = 'perfect'
        elif latest <= ma5 <= ma10 <= ma20 <= ma50: alignment = 'reverse'

    # RSI(14)
    rsi = None
    if n >= 15:
        gains = losses = 0
        for i in range(n-14, n):
            diff = closes[i] - closes[i-1]
            if diff > 0: gains += diff
            else: losses -= diff
        rsi = 100 if losses == 0 else 100 - 100 / (1 + (gains/14) / (losses/14))

    # === 시그널 계산 ===
    signals = []  # (key, label, type)

    # 1) 거래량 폭증
    if n >= 6:
        avg_amt5 = sum(amounts[-6:-1]) / 5 if sum(amounts[-6:-1]) > 0 else 0
        if avg_amt5 > 0 and amounts[-1] > avg_amt5 * 2:
            if pct1d > 0:
                signals.append(('vol_spike_bull', '거래량폭증+상승', 'bull'))
            else:
                signals.append(('vol_spike_bear', '거래량폭증+하락', 'bear'))

    # 2) 이격도
    if gap20 is not None:
        if gap20 <= -5:
            signals.append(('gap_oversold', f'이격도 과침체({gap20:.1f}%)', 'bull'))
        if gap20 >= 5:
            signals.append(('gap_overbought', f'이격도 과열(+{gap20:.1f}%)', 'bear'))

    # 3) MACD (12,26,9)
    if n >= 35:
        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        macd_line = [ema12[i] - ema26[i] for i in range(n)]
        signal9 = ema(macd_line, 9)
        hist_now = macd_line[-1] - signal9[-1]
        hist_prev = macd_line[-2] - signal9[-2]
        if hist_prev <= 0 and hist_now > 0:
            signals.append(('macd_golden', 'MACD 골든크로스', 'bull'))
        if hist_prev >= 0 and hist_now < 0:
            signals.append(('macd_dead', 'MACD 데드크로스', 'bear'))

    # 4) 볼린저밴드 (20, 2σ)
    if n >= 20:
        bb_ma = sum(closes[-20:]) / 20
        bb_var = sum((c - bb_ma)**2 for c in closes[-20:]) / 20
        bb_std = math.sqrt(bb_var)
        bb_upper = bb_ma + 2 * bb_std
        bb_lower = bb_ma - 2 * bb_std
        if latest >= bb_upper:
            signals.append(('bb_upper', 'BB 상단돌파', 'bear'))
        if latest <= bb_lower:
            signals.append(('bb_lower', 'BB 하단이탈', 'bull'))

    # 5) 20일 신고가/신저가
    if n >= 20:
        h20 = max(closes[-20:-1])
        l20 = min(closes[-20:-1])
        if latest >= h20 and pct1d > 0:
            signals.append(('high20', '20일 신고가', 'bull'))
        if latest <= l20 and pct1d < 0:
            signals.append(('low20', '20일 신저가', 'bear'))

    # 6) 연속 상승/하락 3일+
    if n >= 4:
        up_cnt = 0
        for i in range(n-1, 0, -1):
            if closes[i] > closes[i-1]: up_cnt += 1
            else: break
        dn_cnt = 0
        for i in range(n-1, 0, -1):
            if closes[i] < closes[i-1]: dn_cnt += 1
            else: break
        if up_cnt >= 3:
            signals.append(('consec_up', f'연속상승{up_cnt}일', 'bull'))
        if dn_cnt >= 3:
            signals.append(('consec_down', f'연속하락{dn_cnt}일', 'bear'))

    # 7) RSI
    if rsi is not None and rsi <= 30:
        signals.append(('rsi_oversold', f'RSI 과매도({rsi:.0f})', 'bull'))
    if rsi is not None and rsi >= 70:
        signals.append(('rsi_overbought', f'RSI 과매수({rsi:.0f})', 'bear'))

    # 8) MA5/20 골든/데드크로스
    if n >= 22 and ma5 is not None and ma20 is not None:
        prev_closes = closes[:-1]
        pn = len(prev_closes)
        if pn >= 20 and pn >= 5:
            p_ma5 = sum(prev_closes[-5:]) / 5
            p_ma20 = sum(prev_closes[-20:]) / 20
            if p_ma5 <= p_ma20 and ma5 > ma20:
                signals.append(('golden_cross', 'MA골든크로스(5/20)', 'bull'))
            if p_ma5 >= p_ma20 and ma5 < ma20:
                signals.append(('dead_cross', 'MA데드크로스(5/20)', 'bear'))

    name = SECTOR_NAMES.get(code, code)

    # BB/RSI는 양방향 해석 가능 → 중립 분류
    NEUTRAL_KEYS = {'bb_upper', 'bb_lower', 'rsi_oversold', 'rsi_overbought'}
    bull = [s for s in signals if s[2] == 'bull' and s[0] not in NEUTRAL_KEYS]
    bear = [s for s in signals if s[2] == 'bear' and s[0] not in NEUTRAL_KEYS]
    neutral = [s for s in signals if s[0] in NEUTRAL_KEYS]

    return {
        'code': code,
        'name': name,
        'latest': latest,
        'pct1d': pct1d,
        'alignment': alignment,
        'rsi': rsi,
        'signals': signals,
        'bull_count': len(bull),
        'bear_count': len(bear),
        'bull_signals': bull,
        'bear_signals': bear,
        'neutral_signals': neutral,
    }


def format_message(results):
    """텔레그램 메시지 포맷"""
    today = datetime.now().strftime('%Y-%m-%d')

    # 업종만 (지수/규모 제외)
    industry = [r for r in results if r['code'] in INDUSTRY_CODES]

    # 시그널 있는 업종만
    has_bull = [r for r in industry if r['bull_count'] > 0]
    has_bear = [r for r in industry if r['bear_count'] > 0]

    # 호재 많은 순
    has_bull.sort(key=lambda x: -x['bull_count'])
    has_bear.sort(key=lambda x: -x['bear_count'])

    lines = [f'📊 <b>업종 시그널 ({today})</b>']
    lines.append('')

    if has_bull:
        lines.append('🔴 <b>호재 시그널</b>')
        for r in has_bull:
            sigs = ', '.join(s[1] for s in r['bull_signals'])
            pct = f"+{r['pct1d']:.2f}" if r['pct1d'] >= 0 else f"{r['pct1d']:.2f}"
            neu = ', '.join(s[1] for s in r['neutral_signals']) if r['neutral_signals'] else ''
            lines.append(f"  <b>{r['name']}</b> ({pct}%) [{r['bull_count']}개]")
            lines.append(f"    → {sigs}")
            if neu:
                lines.append(f"    ⚪ {neu}")
        lines.append('')

    if has_bear:
        lines.append('🔵 <b>악재 시그널</b>')
        for r in has_bear:
            sigs = ', '.join(s[1] for s in r['bear_signals'])
            pct = f"+{r['pct1d']:.2f}" if r['pct1d'] >= 0 else f"{r['pct1d']:.2f}"
            neu = ', '.join(s[1] for s in r['neutral_signals']) if r['neutral_signals'] else ''
            lines.append(f"  <b>{r['name']}</b> ({pct}%) [{r['bear_count']}개]")
            lines.append(f"    → {sigs}")
            if neu:
                lines.append(f"    ⚪ {neu}")
        lines.append('')

    # 중립만 있는 업종 (호재·악재 0이지만 BB/RSI 시그널 있는 경우)
    neutral_only = [r for r in industry if r['bull_count'] == 0 and r['bear_count'] == 0 and r['neutral_signals']]
    if neutral_only:
        lines.append('⚪ <b>중립 (BB/RSI 양방향)</b>')
        for r in neutral_only:
            neu = ', '.join(s[1] for s in r['neutral_signals'])
            pct = f"+{r['pct1d']:.2f}" if r['pct1d'] >= 0 else f"{r['pct1d']:.2f}"
            lines.append(f"  {r['name']} ({pct}%) — {neu}")
        lines.append('')

    no_sig = [r for r in industry if r['bull_count'] == 0 and r['bear_count'] == 0 and not r['neutral_signals']]
    lines.append(f'시그널 없음: {len(no_sig)}개 업종')

    # 요약
    bull2 = len([r for r in industry if r['bull_count'] >= 2])
    bear2 = len([r for r in industry if r['bear_count'] >= 2])
    lines.append(f'\n🔴 호재 2개↑: {bull2}개 업종 | 🔵 악재 2개↑: {bear2}개 업종')

    return '\n'.join(lines)


def main():
    print(f'[{datetime.now():%Y-%m-%d %H:%M}] sector_alert 시작')

    conn = oracledb.connect(
        user='ADMIN',
        password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))

    grouped = fetch_data(conn, days=120)
    conn.close()

    results = []
    for code, data in grouped.items():
        r = compute_signals(code, data)
        if r:
            results.append(r)

    msg = format_message(results)

    # DM만 발송 (채널 X)
    ok = send_dm(msg)
    print(f'  텔레그램 발송: {"성공" if ok else "실패"}')
    print(f'  업종 {len(results)}개 분석 완료')


if __name__ == '__main__':
    main()
