# ── 아래 코드를 api_server.py의 if __name__ == '__main__': 바로 위에 추가 ──

@app.route('/api/futures-investor')
def futures_investor():
    """
    선물 투자자별 매매동향.
    ?days=90  (기본: 90)
    반환: [{dt, institution_qty, foreign_qty, ... , foreign_cum_qty, equiv_idx}]
    """
    days = int(request.args.get('days', 365))

    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT TO_CHAR(trade_date,'YYYY-MM-DD') AS dt,
        institution_qty, corp_other_qty, individual_qty, foreign_qty,
        institution_amt, corp_other_amt, individual_amt, foreign_amt
        FROM futures_investor
        WHERE trade_date >= TRUNC(SYSDATE) - :days
        ORDER BY trade_date""", {'days': days})
    data = rows_to_list(cur, cur.fetchall())
    cur.close(); conn.close()

    # 누적 순매수 & 환산지수 계산
    cum_qty = 0
    cum_amt = 0
    for row in data:
        cum_qty += (row.get('foreign_qty') or 0)
        cum_amt += (row.get('foreign_amt') or 0)
        row['foreign_cum_qty'] = cum_qty
        row['foreign_cum_amt'] = cum_amt
        if cum_qty != 0:
            row['equiv_idx'] = round(cum_amt / (cum_qty * 250000), 2)
        else:
            row['equiv_idx'] = 0

    return jsonify({'count': len(data), 'data': data})
