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

def _convert(val):
    """Oracle 타입 → Python 기본 타입 변환"""
    if val is None: return None
    if isinstance(val, datetime): return val.strftime('%Y-%m-%d %H:%M:%S')
    if hasattr(val, 'read'): return val.read()  # LOB → str
    return val

def rows_to_list(cur, rows):
    cols = [c[0].lower() for c in cur.description]
    return [dict(zip(cols, [_convert(v) for v in r])) for r in rows]

def row_to_dict(cur, row):
    cols = [c[0].lower() for c in cur.description]
    return dict(zip(cols, [_convert(v) for v in row]))

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
    build_year_from = request.args.get('build_year_from', '')
    build_year_to = request.args.get('build_year_to', '')
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

    # 금액 범위 (매매=price, 전세/월세=deposit)
    if price_min:
        where.append("(CASE WHEN deal_type='S' THEN price ELSE NVL(deposit,0) END)>=:pmin")
        params['pmin'] = int(price_min)
    if price_max:
        where.append("(CASE WHEN deal_type='S' THEN price ELSE NVL(deposit,0) END)<=:pmax")
        params['pmax'] = int(price_max)

    # 건물명 검색 (쉼표로 여러 개 OR 검색)
    if name:
        names = [n.strip() for n in name.split(',') if n.strip()]
        if len(names) == 1:
            where.append("UPPER(name) LIKE '%'||UPPER(:name)||'%'")
            params['name'] = names[0]
        elif names:
            or_parts = []
            for i, n in enumerate(names):
                or_parts.append(f"UPPER(name) LIKE '%'||UPPER(:nm{i})||'%'")
                params[f'nm{i}'] = n
            where.append('(' + ' OR '.join(or_parts) + ')')

    # 준공년도
    if build_year_from:
        where.append('build_year>=:byf'); params['byf'] = int(build_year_from)
    if build_year_to:
        where.append('build_year<=:byt'); params['byt'] = int(build_year_to)

    w = ' AND '.join(where)
    conn = get_conn(); cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM real_estate WHERE {w}", params)
    total = cur.fetchone()[0]
    cur.execute(f"""SELECT * FROM (SELECT a.*, ROWNUM rn FROM (
        SELECT region, name, dong, area_m2 AS area, floor_no AS floor, deal_type, price, deposit, monthly_rent,
               deal_year, deal_month, deal_day, build_year
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
        where.append("(UPPER(title) LIKE '%'||UPPER(:q)||'%' OR UPPER(CAST(content AS VARCHAR2(4000))) LIKE '%'||UPPER(:q2)||'%')")
        params['q'] = search
        params['q2'] = search
    w = ' AND '.join(where)
    conn = get_conn(); cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM posts WHERE {w}", params)
    total = cur.fetchone()[0]
    offset = (page - 1) * per
    cur.execute(f"""SELECT * FROM (SELECT a.*, ROWNUM rn FROM (
        SELECT id, category, title, author, is_pinned, views, created_at, updated_at
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

# ══ notes (투자메모·일지) ══
@app.route('/api/note-categories', methods=['GET'])
def list_note_categories():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id, name, sort_order FROM note_categories ORDER BY sort_order, id")
    data = rows_to_list(cur, cur.fetchall()); cur.close(); conn.close()
    return jsonify(data)

@app.route('/api/note-categories', methods=['POST'])
def add_note_category():
    d = request.get_json()
    if not d: return jsonify({'error': 'JSON 필요'}), 400
    name = (d.get('name') or '').strip()
    if not name or len(name) > 20: return jsonify({'error': '1~20자 카테고리명을 입력하세요.'}), 400
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT MAX(sort_order) FROM note_categories"); mx = cur.fetchone()[0] or 0
    cur.execute("INSERT INTO note_categories (name, sort_order) VALUES (:n, :s)", {'n': name, 's': mx + 1})
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True}), 201

@app.route('/api/note-categories/<int:cat_id>', methods=['DELETE'])
def delete_note_category(cat_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM notes WHERE category=:c", {'c': str(cat_id)})
    cnt = cur.fetchone()[0]
    if cnt > 0: cur.close(); conn.close(); return jsonify({'error': f'글 {cnt}건이 있어 삭제 불가.'}), 400
    cur.execute("DELETE FROM note_categories WHERE id=:id", {'id': cat_id})
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/notes', methods=['GET'])
def list_notes():
    page = int(request.args.get('page', 1))
    per = int(request.args.get('per_page', 30))
    category = request.args.get('category', '')
    search = request.args.get('q', '')
    where = ['1=1']; params = {}
    if category: where.append('category=:cat'); params['cat'] = category
    if search:
        where.append("(UPPER(NVL(title,'')) LIKE '%'||UPPER(:q)||'%' OR UPPER(CAST(content AS VARCHAR2(4000))) LIKE '%'||UPPER(:q2)||'%')")
        params['q'] = search; params['q2'] = search
    w = ' AND '.join(where)
    conn = get_conn(); cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM notes WHERE {w}", params)
    total = cur.fetchone()[0]
    offset = (page - 1) * per
    cur.execute(f"""SELECT * FROM (SELECT a.*, ROWNUM rn FROM (
        SELECT id, category, title, author, is_pinned, views, created_at, updated_at
        FROM notes WHERE {w} ORDER BY is_pinned DESC NULLS LAST, created_at DESC
    ) a WHERE ROWNUM <= :maxrow) WHERE rn > :minrow""",
        {**params, 'maxrow': offset + per, 'minrow': offset})
    notes = rows_to_list(cur, cur.fetchall())
    for n in notes:
        n['created_at'] = dt_str(n.get('created_at'))
        n['updated_at'] = dt_str(n.get('updated_at'))
    cur.close(); conn.close()
    return jsonify({'total': total, 'page': page, 'per_page': per, 'pages': (total+per-1)//per, 'data': notes})

@app.route('/api/notes/<int:note_id>', methods=['GET'])
def get_note(note_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE notes SET views=NVL(views,0)+1 WHERE id=:id", {'id': note_id})
    conn.commit()
    cur.execute("SELECT * FROM notes WHERE id=:id", {'id': note_id})
    row = cur.fetchone()
    if not row: cur.close(); conn.close(); return jsonify({'error': '글을 찾을 수 없습니다.'}), 404
    note = row_to_dict(cur, row)
    note['created_at'] = dt_str(note.get('created_at'))
    note['updated_at'] = dt_str(note.get('updated_at'))
    cur.close(); conn.close()
    return jsonify(note)

@app.route('/api/notes', methods=['POST'])
def create_note():
    d = request.get_json()
    if not d: return jsonify({'error': 'JSON 필요'}), 400
    title = (d.get('title') or '').strip()
    content = (d.get('content') or '').strip()
    author = (d.get('author') or '').strip() or '스윙파머'
    category = d.get('category', '')
    is_pinned = 1 if d.get('pinned') else 0
    if not content: return jsonify({'error': '내용을 입력하세요.'}), 400
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO notes (category, title, content, author, is_pinned, views, created_at)
        VALUES (:cat, :title, :content, :author, :pinned, 0, SYSTIMESTAMP)""",
        {'cat': category, 'title': title, 'content': content, 'author': author, 'pinned': is_pinned})
    conn.commit()
    cur.execute("SELECT MAX(id) FROM notes"); new_id = cur.fetchone()[0]
    cur.close(); conn.close()
    return jsonify({'ok': True, 'id': new_id}), 201

@app.route('/api/notes/<int:note_id>', methods=['PUT'])
def update_note(note_id):
    d = request.get_json()
    if not d: return jsonify({'error': 'JSON 필요'}), 400
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM notes WHERE id=:id", {'id': note_id})
    if not cur.fetchone(): cur.close(); conn.close(); return jsonify({'error': '글을 찾을 수 없습니다.'}), 404
    title = (d.get('title') or '').strip()
    content = (d.get('content') or '').strip()
    author = (d.get('author') or '').strip() or '스윙파머'
    category = d.get('category', '')
    is_pinned = 1 if d.get('pinned') else 0
    if not content: cur.close(); conn.close(); return jsonify({'error': '내용을 입력하세요.'}), 400
    cur.execute("""UPDATE notes SET title=:title, author=:author, content=:content,
        category=:cat, is_pinned=:pinned, updated_at=SYSTIMESTAMP WHERE id=:id""",
        {'title': title, 'author': author, 'content': content, 'cat': category, 'pinned': is_pinned, 'id': note_id})
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/notes/<int:note_id>', methods=['DELETE'])
def delete_note(note_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM notes WHERE id=:id", {'id': note_id})
    if not cur.fetchone(): cur.close(); conn.close(); return jsonify({'error': '글을 찾을 수 없습니다.'}), 404
    cur.execute("DELETE FROM notes WHERE id=:id", {'id': note_id})
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True})

# ══ exchange rates (수출입은행) ══
@app.route('/api/rates/exchange')
def rates_exchange():
    """환율 조회. ?cur=USD,JPY,EUR &days=90 &from=2026-01-01 &to=2026-09-29"""
    cur_filter = request.args.get('cur', '')  # 쉼표 구분 통화코드
    days = request.args.get('days', '')
    date_from = request.args.get('from', '')
    date_to = request.args.get('to', '')
    latest = request.args.get('latest', '')  # latest=1 → 최신 1일

    where = []; params = {}
    if cur_filter:
        curs = [c.strip() for c in cur_filter.split(',') if c.strip()]
        if curs:
            ph = ','.join([f':c{i}' for i in range(len(curs))])
            where.append(f'cur_unit IN ({ph})')
            for i, c in enumerate(curs): params[f'c{i}'] = c

    if latest == '1':
        where.append('rate_date = (SELECT MAX(rate_date) FROM exchange_rates)')
    else:
        if days:
            where.append(f"rate_date >= TRUNC(SYSDATE) - :days")
            params['days'] = int(days)
        if date_from:
            where.append("rate_date >= TO_DATE(:df, 'YYYY-MM-DD')")
            params['df'] = date_from
        if date_to:
            where.append("rate_date <= TO_DATE(:dt, 'YYYY-MM-DD')")
            params['dt'] = date_to

    w = ' AND '.join(where) if where else '1=1'
    conn = get_conn(); cur = conn.cursor()
    cur.execute(f"""SELECT TO_CHAR(rate_date,'YYYY-MM-DD') AS rate_date, cur_unit, cur_nm,
        deal_bas_r, ttb, tts, bkpr, kftc_deal_bas_r, kftc_bkpr,
        yy_efee_r, ten_dd_efee_r
        FROM exchange_rates WHERE {w} ORDER BY rate_date DESC, cur_unit""", params)
    data = rows_to_list(cur, cur.fetchall())
    cur.close(); conn.close()
    return jsonify({'count': len(data), 'data': data})

@app.route('/api/rates/exchange/currencies')
def rates_currencies():
    """DB에 있는 통화 목록."""
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT cur_unit, cur_nm, COUNT(*) cnt,
        TO_CHAR(MIN(rate_date),'YYYY-MM-DD') first_date,
        TO_CHAR(MAX(rate_date),'YYYY-MM-DD') last_date
        FROM exchange_rates GROUP BY cur_unit, cur_nm ORDER BY cnt DESC""")
    data = rows_to_list(cur, cur.fetchall())
    cur.close(); conn.close()
    return jsonify(data)

@app.route('/api/rates/interest')
def rates_interest():
    """금리 조회. ?type=AP02,AP03 &days=90 &item=한국은행 기준금리"""
    dtype = request.args.get('type', '')
    days = request.args.get('days', '')
    date_from = request.args.get('from', '')
    date_to = request.args.get('to', '')
    item = request.args.get('item', '')
    latest = request.args.get('latest', '')

    where = []; params = {}
    if dtype:
        types = [t.strip() for t in dtype.split(',') if t.strip()]
        if types:
            ph = ','.join([f':t{i}' for i in range(len(types))])
            where.append(f'data_type IN ({ph})')
            for i, t in enumerate(types): params[f't{i}'] = t
    if item:
        where.append("item_nm LIKE '%'||:item||'%'")
        params['item'] = item
    if latest == '1':
        where.append('rate_date = (SELECT MAX(rate_date) FROM interest_rates)')
    else:
        if days:
            where.append(f"rate_date >= TRUNC(SYSDATE) - :days")
            params['days'] = int(days)
        if date_from:
            where.append("rate_date >= TO_DATE(:df, 'YYYY-MM-DD')")
            params['df'] = date_from
        if date_to:
            where.append("rate_date <= TO_DATE(:dt, 'YYYY-MM-DD')")
            params['dt'] = date_to

    w = ' AND '.join(where) if where else '1=1'
    conn = get_conn(); cur = conn.cursor()
    cur.execute(f"""SELECT TO_CHAR(rate_date,'YYYY-MM-DD') AS rate_date,
        data_type, item_code, item_nm, rate
        FROM interest_rates WHERE {w} ORDER BY rate_date DESC, data_type, item_code""", params)
    data = rows_to_list(cur, cur.fetchall())
    cur.close(); conn.close()
    return jsonify({'count': len(data), 'data': data})

@app.route('/api/rates/interest/items')
def rates_interest_items():
    """DB에 있는 금리 항목 목록."""
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT data_type, item_code, item_nm, COUNT(*) cnt,
        TO_CHAR(MIN(rate_date),'YYYY-MM-DD') first_date,
        TO_CHAR(MAX(rate_date),'YYYY-MM-DD') last_date
        FROM interest_rates GROUP BY data_type, item_code, item_nm
        ORDER BY data_type, cnt DESC""")
    data = rows_to_list(cur, cur.fetchall())
    cur.close(); conn.close()
    return jsonify(data)

# ══ gold prices (금시세) ══
@app.route('/api/rates/gold')
def rates_gold():
    """금시세 조회. ?days=365 &from=2020-01-01 &to=2026-09-29 &latest=1 &unit=usd|krw"""
    days = request.args.get('days', '')
    date_from = request.args.get('from', '')
    date_to = request.args.get('to', '')
    latest = request.args.get('latest', '')
    unit = request.args.get('unit', '')  # usd or krw

    where = []; params = {}
    if latest == '1':
        where.append('price_date = (SELECT MAX(price_date) FROM gold_prices)')
    else:
        if days:
            where.append("price_date >= TRUNC(SYSDATE) - :days")
            params['days'] = int(days)
        if date_from:
            where.append("price_date >= TO_DATE(:df, 'YYYY-MM-DD')")
            params['df'] = date_from
        if date_to:
            where.append("price_date <= TO_DATE(:dt, 'YYYY-MM-DD')")
            params['dt'] = date_to

    w = ' AND '.join(where) if where else '1=1'
    conn = get_conn(); cur = conn.cursor()
    cur.execute(f"""SELECT TO_CHAR(price_date,'YYYY-MM-DD') AS price_date,
        price_usd, price_krw_g, usd_krw, source
        FROM gold_prices WHERE {w} ORDER BY price_date DESC""", params)
    data = rows_to_list(cur, cur.fetchall())
    cur.close(); conn.close()
    return jsonify({'count': len(data), 'data': data})

@app.route('/api/rates/gold/summary')
def rates_gold_summary():
    """금시세 요약 (총 건수, 범위, KRW 변환 건수)."""
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT COUNT(*) total,
        COUNT(price_krw_g) krw_count,
        TO_CHAR(MIN(price_date),'YYYY-MM-DD') first_date,
        TO_CHAR(MAX(price_date),'YYYY-MM-DD') last_date
        FROM gold_prices""")
    data = rows_to_list(cur, cur.fetchall())
    cur.close(); conn.close()
    return jsonify(data[0] if data else {})

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
