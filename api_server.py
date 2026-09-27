#!/usr/bin/env python3
"""
스윙파머 API 서버 (Flask + Oracle Autonomous DB)
비밀번호 인증 없음 — 보안은 클라이언트 Firebase Auth 게이트에 위임
보류A(보안1단계)에서 서버 토큰 검증 추가 예정
"""
import os
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import oracledb

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

app = Flask(__name__)
CORS(app, origins=['https://swingfarmer.github.io'])

WALLET_DIR = os.path.expanduser('~/wallet')
DB_USER = 'ADMIN'
DB_PASSWORD = os.environ.get('ORACLE_DB_PASSWORD', '')
DSN = 'db1007_medium'

def get_conn():
    return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DSN,
        config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))

def rows_to_list(cur, rows):
    cols = [c[0].lower() for c in cur.description]
    return [dict(zip(cols, r)) for r in rows]

def row_to_dict(cur, row):
    cols = [c[0].lower() for c in cur.description]
    return dict(zip(cols, row))

def dt_str(val):
    if val is None: return None
    if isinstance(val, datetime): return val.strftime('%Y-%m-%d %H:%M:%S')
    return str(val)

# ── health ──
@app.route('/api/health')
def health():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM real_estate")
        cnt = cur.fetchone()[0]; cur.close(); conn.close()
        return jsonify({'status': 'ok', 'real_estate_count': cnt})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ══ realestate ══
@app.route('/api/realestate/regions')
def re_regions():
    prop = request.args.get('prop_type', 'APT')
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT region, COUNT(*) cnt FROM real_estate WHERE prop_type=:1 GROUP BY region ORDER BY region", [prop])
    data = [{'region': r[0], 'count': r[1]} for r in cur.fetchall()]
    cur.close(); conn.close()
    return jsonify(data)

@app.route('/api/realestate/dongs')
def re_dongs():
    region = request.args.get('region', '')
    prop = request.args.get('prop_type', 'APT')
    conn = get_conn(); cur = conn.cursor()
    # 다중 지역 지원 (쉼표 구분)
    regions = [r.strip() for r in region.split(',') if r.strip()]
    if len(regions) == 1:
        cur.execute("SELECT DISTINCT dong FROM real_estate WHERE region=:1 AND prop_type=:2 ORDER BY dong", [regions[0], prop])
    elif len(regions) > 1:
        ph = ','.join([f':r{i}' for i in range(len(regions))])
        p = {f'r{i}': regions[i] for i in range(len(regions))}
        p['prop'] = prop
        cur.execute(f"SELECT DISTINCT dong FROM real_estate WHERE region IN ({ph}) AND prop_type=:prop ORDER BY dong", p)
    else:
        cur.execute("SELECT DISTINCT dong FROM real_estate WHERE prop_type=:1 ORDER BY dong", [prop])
    data = [r[0] for r in cur.fetchall()]; cur.close(); conn.close()
    return jsonify(data)

@app.route('/api/realestate/search')
def re_search():
    prop = request.args.get('prop_type', 'APT')
    region = request.args.get('region', '')
    dong = request.args.get('dong', '')
    deal_type_str = request.args.get('deal_type', '')  # 쉼표 구분 문자열
    year_from = request.args.get('year_from', '')
    year_to = request.args.get('year_to', '')
    area_min = request.args.get('area_min', '')
    area_max = request.args.get('area_max', '')
    area_range = request.args.get('area', '')  # "60-85" 형태 호환
    price_min = request.args.get('price_min', '')
    price_max = request.args.get('price_max', '')
    name = request.args.get('name', '')
    limit = int(request.args.get('limit', request.args.get('per_page', 500)))
    offset = int(request.args.get('offset', 0))
    # page 파라미터 호환
    page = request.args.get('page', '')
    if page and not request.args.get('offset', ''):
        offset = (int(page) - 1) * limit

    where = ['prop_type=:prop']; params = {'prop': prop}

    # 다중 지역 (쉼표 구분)
    if region:
        regions = [r.strip() for r in region.split(',') if r.strip()]
        if len(regions) == 1:
            where.append('region=:region'); params['region'] = regions[0]
        else:
            ph = ','.join([f':rg{i}' for i in range(len(regions))])
            where.append(f'region IN ({ph})')
            for i, r in enumerate(regions): params[f'rg{i}'] = r
    if dong: where.append('dong=:dong'); params['dong'] = dong

    # 거래유형 (쉼표 구분)
    if deal_type_str:
        dts = [d.strip() for d in deal_type_str.split(',') if d.strip()]
        if dts and len(dts) < 3:
            ph = ','.join([f':dt{i}' for i in range(len(dts))])
            where.append(f'deal_type IN ({ph})')
            for i, dt in enumerate(dts): params[f'dt{i}'] = dt

    if year_from: where.append('deal_year>=:yf'); params['yf'] = int(year_from)
    if year_to: where.append('deal_year<=:yt'); params['yt'] = int(year_to)

    # 면적: 직접 입력 우선, area 파라미터 호환
    if area_min:
        where.append('area_m2>=:amin'); params['amin'] = float(area_min)
    if area_max:
        where.append('area_m2<=:amax'); params['amax'] = float(area_max)
    if area_range and not area_min and not area_max:
        if '-' in area_range:
            parts = area_range.split('-')
            if parts[0]: where.append('area_m2>=:amin'); params['amin'] = float(parts[0])
            if parts[1]: where.append('area_m2<=:amax'); params['amax'] = float(parts[1])

    # 금액 범위
    if price_min: where.append('price>=:pmin'); params['pmin'] = int(price_min)
    if price_max: where.append('price<=:pmax'); params['pmax'] = int(price_max)

    # 건물명 검색
    if name:
        where.append("UPPER(name) LIKE '%'||UPPER(:name)||'%'")
        params['name'] = name

    w = ' AND '.join(where)
    conn = get_conn(); cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM real_estate WHERE {w}", params)
    total = cur.fetchone()[0]
    cur.execute(f"""SELECT * FROM (SELECT a.*, ROWNUM rn FROM (
        SELECT region, name, dong, area_m2 AS area, floor_no AS floor, deal_type, price, deposit, monthly_rent,
               deal_year, deal_month, deal_day
        FROM real_estate WHERE {w}
        ORDER BY deal_year DESC, deal_month DESC, deal_day DESC
    ) a WHERE ROWNUM <= :maxrow) WHERE rn > :minrow""",
        {**params, 'maxrow': offset + limit, 'minrow': offset})
    data = rows_to_list(cur, cur.fetchall())
    cur.close(); conn.close()
    return jsonify({'total': total, 'data': data})

@app.route('/api/realestate/stats')
def re_stats():
    prop = request.args.get('prop_type', 'APT')
    region = request.args.get('region', '')
    where = ['prop_type=:prop']; params = {'prop': prop}
    if region:
        regions = [r.strip() for r in region.split(',') if r.strip()]
        if len(regions) == 1:
            where.append('region=:region'); params['region'] = regions[0]
        else:
            ph = ','.join([f':rg{i}' for i in range(len(regions))])
            where.append(f'region IN ({ph})')
            for i, r in enumerate(regions): params[f'rg{i}'] = r
    w = ' AND '.join(where)
    conn = get_conn(); cur = conn.cursor()

    # summary (매매 기준)
    cur.execute(f"""SELECT COUNT(*), ROUND(AVG(price)), MAX(price), MIN(price)
        FROM real_estate WHERE {w} AND deal_type='S' AND price>0""", params)
    row = cur.fetchone()
    summary = {'count': row[0] or 0, 'avg_price': row[1] or 0, 'max_price': row[2] or 0, 'min_price': row[3] or 0}

    # top 아파트
    cur.execute(f"""SELECT * FROM (
        SELECT name, COUNT(*) cnt FROM real_estate WHERE {w} AND name IS NOT NULL
        GROUP BY name ORDER BY cnt DESC
    ) WHERE ROWNUM <= 5""", params)
    top_apts = [{'name': r[0], 'count': r[1]} for r in cur.fetchall()]

    # 연도별
    cur.execute(f"""SELECT deal_year AS year, ROUND(AVG(price)) avg_price, COUNT(*) count
        FROM real_estate WHERE {w} AND deal_type='S' AND price>0
        GROUP BY deal_year ORDER BY deal_year""", params)
    yearly = rows_to_list(cur, cur.fetchall())

    cur.close(); conn.close()
    return jsonify({'summary': summary, 'top_apts': top_apts, 'yearly': yearly})

# ══ categories ══
@app.route('/api/categories', methods=['GET'])
def list_categories():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id, name, sort_order FROM categories ORDER BY sort_order, id")
    data = rows_to_list(cur, cur.fetchall()); cur.close(); conn.close()
    return jsonify(data)

@app.route('/api/categories', methods=['POST'])
def add_category():
    d = request.get_json()
    if not d: return jsonify({'error': 'JSON 필요'}), 400
    name = (d.get('name') or '').strip()
    if not name: return jsonify({'error': '카테고리명을 입력하세요.'}), 400
    if len(name) > 20: return jsonify({'error': '20자 이내로 입력하세요.'}), 400
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT MAX(sort_order) FROM categories")
    mx = cur.fetchone()[0] or 0
    cur.execute("INSERT INTO categories (name, sort_order) VALUES (:n, :s)", {'n': name, 's': mx + 1})
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True}), 201

@app.route('/api/categories/<int:cat_id>', methods=['PUT'])
def update_category(cat_id):
    d = request.get_json()
    if not d: return jsonify({'error': 'JSON 필요'}), 400
    name = (d.get('name') or '').strip()
    if not name: return jsonify({'error': '카테고리명을 입력하세요.'}), 400
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE categories SET name=:n WHERE id=:id", {'n': name, 'id': cat_id})
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/categories/<int:cat_id>', methods=['DELETE'])
def delete_category(cat_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM posts WHERE category=:c", {'c': str(cat_id)})
    cnt = cur.fetchone()[0]
    if cnt > 0:
        cur.close(); conn.close()
        return jsonify({'error': f'글 {cnt}건이 있어 삭제 불가. 글을 먼저 이동하세요.'}), 400
    cur.execute("DELETE FROM categories WHERE id=:id", {'id': cat_id})
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True})

# ══ posts ══
@app.route('/api/posts', methods=['GET'])
def list_posts():
    page = int(request.args.get('page', 1))
    per = int(request.args.get('per_page', 20))
    category = request.args.get('category', '')
    search = request.args.get('q', '')
    where = ['1=1']; params = {}
    if category: where.append('category=:cat'); params['cat'] = category
    if search:
        where.append("(UPPER(title) LIKE '%'||UPPER(:q)||'%' OR UPPER(content) LIKE '%'||UPPER(:q)||'%')")
        params['q'] = search
    w = ' AND '.join(where)
    conn = get_conn(); cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM posts WHERE {w}", params)
    total = cur.fetchone()[0]
    offset = (page - 1) * per
    cur.execute(f"""SELECT * FROM (SELECT a.*, ROWNUM rn FROM (
        SELECT id, category, title, author, content, is_pinned, views, created_at, updated_at
        FROM posts WHERE {w} ORDER BY is_pinned DESC NULLS LAST, created_at DESC
    ) a WHERE ROWNUM <= :maxrow) WHERE rn > :minrow""",
        {**params, 'maxrow': offset + per, 'minrow': offset})
    posts = rows_to_list(cur, cur.fetchall())
    if posts:
        ids = [p['id'] for p in posts]
        ph = ','.join([f':cid{i}' for i in range(len(ids))])
        cp = {f'cid{i}': ids[i] for i in range(len(ids))}
        cur.execute(f"SELECT post_id, COUNT(*) cnt FROM comments WHERE post_id IN ({ph}) GROUP BY post_id", cp)
        cc = {r[0]: r[1] for r in cur.fetchall()}
        for p in posts:
            p['comment_count'] = cc.get(p['id'], 0)
            p['created_at'] = dt_str(p.get('created_at'))
            p['updated_at'] = dt_str(p.get('updated_at'))
    cur.close(); conn.close()
    return jsonify({'total': total, 'page': page, 'per_page': per, 'pages': (total+per-1)//per, 'data': posts})

@app.route('/api/posts/<int:post_id>', methods=['GET'])
def get_post(post_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE posts SET views=NVL(views,0)+1 WHERE id=:id", {'id': post_id})
    conn.commit()
    cur.execute("SELECT * FROM posts WHERE id=:id", {'id': post_id})
    row = cur.fetchone()
    if not row: cur.close(); conn.close(); return jsonify({'error': '글을 찾을 수 없습니다.'}), 404
    post = row_to_dict(cur, row)
    post['created_at'] = dt_str(post.get('created_at'))
    post['updated_at'] = dt_str(post.get('updated_at'))
    cur.execute("SELECT id,post_id,author,content,created_at FROM comments WHERE post_id=:pid ORDER BY created_at", {'pid': post_id})
    comments = rows_to_list(cur, cur.fetchall())
    for c in comments: c['created_at'] = dt_str(c.get('created_at'))
    post['comments'] = comments; cur.close(); conn.close()
    return jsonify(post)

@app.route('/api/posts', methods=['POST'])
def create_post():
    d = request.get_json()
    if not d: return jsonify({'error': 'JSON 필요'}), 400
    title = (d.get('title') or '').strip()
    content = (d.get('content') or '').strip()
    author = (d.get('author') or '').strip() or '익명'
    category = d.get('category', '')
    pinned = 1 if d.get('pinned') else 0
    if not title: return jsonify({'error': '제목을 입력하세요.'}), 400
    if not content: return jsonify({'error': '내용을 입력하세요.'}), 400
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO posts (category, title, author, content, is_pinned, views, created_at)
        VALUES (:cat, :title, :author, :content, :pinned, 0, SYSTIMESTAMP)""",
        {'cat': category, 'title': title, 'author': author, 'content': content, 'pinned': pinned})
    conn.commit()
    cur.execute("SELECT MAX(id) FROM posts"); new_id = cur.fetchone()[0]
    cur.close(); conn.close()
    return jsonify({'ok': True, 'id': new_id}), 201

@app.route('/api/posts/<int:post_id>', methods=['PUT'])
def update_post(post_id):
    d = request.get_json()
    if not d: return jsonify({'error': 'JSON 필요'}), 400
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM posts WHERE id=:id", {'id': post_id})
    if not cur.fetchone(): cur.close(); conn.close(); return jsonify({'error': '글을 찾을 수 없습니다.'}), 404
    title = (d.get('title') or '').strip()
    content = (d.get('content') or '').strip()
    author = (d.get('author') or '').strip() or '익명'
    category = d.get('category', '')
    pinned = 1 if d.get('pinned') else 0
    if not title or not content: cur.close(); conn.close(); return jsonify({'error': '제목과 내용을 입력하세요.'}), 400
    cur.execute("""UPDATE posts SET title=:title, author=:author, content=:content,
        category=:cat, is_pinned=:pinned, updated_at=SYSTIMESTAMP WHERE id=:id""",
        {'title': title, 'author': author, 'content': content, 'cat': category, 'pinned': pinned, 'id': post_id})
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
def delete_post(post_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM posts WHERE id=:id", {'id': post_id})
    if not cur.fetchone(): cur.close(); conn.close(); return jsonify({'error': '글을 찾을 수 없습니다.'}), 404
    cur.execute("DELETE FROM comments WHERE post_id=:id", {'id': post_id})
    cur.execute("DELETE FROM posts WHERE id=:id", {'id': post_id})
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True})

# ══ comments ══
@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
def add_comment(post_id):
    d = request.get_json()
    if not d: return jsonify({'error': 'JSON 필요'}), 400
    author = (d.get('author') or '').strip() or '익명'
    content = (d.get('content') or '').strip()
    if not content: return jsonify({'error': '댓글 내용을 입력하세요.'}), 400
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM posts WHERE id=:id", {'id': post_id})
    if not cur.fetchone(): cur.close(); conn.close(); return jsonify({'error': '글을 찾을 수 없습니다.'}), 404
    cur.execute("INSERT INTO comments (post_id,author,content,created_at) VALUES (:pid,:a,:c,SYSTIMESTAMP)",
        {'pid': post_id, 'a': author, 'c': content})
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True}), 201

@app.route('/api/comments/<int:comment_id>', methods=['DELETE'])
def delete_comment(comment_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM comments WHERE id=:id", {'id': comment_id})
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
