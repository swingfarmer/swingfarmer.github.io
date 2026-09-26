#!/usr/bin/env python3
"""
스윙파머 API 서버 (Flask + Oracle Autonomous DB)
- /api/health
- /api/realestate/*   (실거래가)
- /api/posts/*        (게시판)
- /api/comments/*     (댓글)

VM 배포: ~/api_server.py → sudo systemctl restart swingfarmer-api
"""

import os, hashlib, json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import oracledb

# ── 환경변수 로드 ──
def load_env():
    env_file = os.path.expanduser('~/.env_secrets')
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('export '):
                    line = line[7:]
                if '=' in line:
                    k, v = line.split('=', 1)
                    v = v.strip().strip('"').strip("'")
                    os.environ.setdefault(k.strip(), v)

load_env()

app = Flask(__name__)
CORS(app, origins=['https://swingfarmer.github.io'])

# ── DB 연결 ──
WALLET_DIR = os.path.expanduser('~/wallet')
DB_USER = 'ADMIN'
DB_PASSWORD = os.environ.get('ORACLE_DB_PASSWORD', '')
DSN = 'db1007_medium'

def get_conn():
    return oracledb.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        dsn=DSN,
        config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', '')
    )

# ── 헬퍼 ──
def row_to_dict(cursor, row):
    cols = [c[0].lower() for c in cursor.description]
    return dict(zip(cols, row))

def rows_to_list(cursor, rows):
    cols = [c[0].lower() for c in cursor.description]
    return [dict(zip(cols, r)) for r in rows]

def dt_str(val):
    """Oracle datetime → 문자열"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime('%Y-%m-%d %H:%M:%S')
    return str(val)

def hash_pw(pw):
    """SHA-256 해시 (프론트와 동일한 salt)"""
    return hashlib.sha256((pw + '_sf_salt_2026').encode()).hexdigest()

# 관리자 비밀번호 해시 (기존 board와 동일)
ADMIN_PW_HASH = '7046371e5d7b0d17221938e25d12b146ddc83a20546fb86eab16cb1d5c3a4014'

# ============================================================
#  /api/health
# ============================================================
@app.route('/api/health')
def health():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM real_estate")
        cnt = cur.fetchone()[0]
        cur.close()
        conn.close()
        return jsonify({'status': 'ok', 'real_estate_count': cnt})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============================================================
#  /api/realestate/* (기존 유지)
# ============================================================
@app.route('/api/realestate/regions')
def re_regions():
    prop = request.args.get('prop_type', 'APT')
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT region FROM real_estate WHERE prop_type=:1 ORDER BY region",
        [prop]
    )
    data = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()
    return jsonify(data)

@app.route('/api/realestate/dongs')
def re_dongs():
    region = request.args.get('region', '')
    prop = request.args.get('prop_type', 'APT')
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT dong FROM real_estate WHERE region=:1 AND prop_type=:2 ORDER BY dong",
        [region, prop]
    )
    data = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()
    return jsonify(data)

@app.route('/api/realestate/search')
def re_search():
    prop = request.args.get('prop_type', 'APT')
    region = request.args.get('region', '')
    dong = request.args.get('dong', '')
    deal_types = request.args.getlist('deal_type')
    year_from = request.args.get('year_from', '')
    year_to = request.args.get('year_to', '')
    area_min = request.args.get('area_min', '')
    area_max = request.args.get('area_max', '')
    page = int(request.args.get('page', 1))
    per = int(request.args.get('per_page', 50))

    where = ['prop_type=:prop']
    params = {'prop': prop}

    if region:
        where.append('region=:region')
        params['region'] = region
    if dong:
        where.append('dong=:dong')
        params['dong'] = dong
    if deal_types:
        placeholders = ','.join([f':dt{i}' for i in range(len(deal_types))])
        where.append(f'deal_type IN ({placeholders})')
        for i, dt in enumerate(deal_types):
            params[f'dt{i}'] = dt
    if year_from:
        where.append('deal_year>=:yf')
        params['yf'] = int(year_from)
    if year_to:
        where.append('deal_year<=:yt')
        params['yt'] = int(year_to)
    if area_min:
        where.append('area>=:amin')
        params['amin'] = float(area_min)
    if area_max:
        where.append('area<=:amax')
        params['amax'] = float(area_max)

    w = ' AND '.join(where)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) FROM real_estate WHERE {w}", params)
    total = cur.fetchone()[0]

    offset = (page - 1) * per
    cur.execute(f"""
        SELECT * FROM (
            SELECT a.*, ROWNUM rn FROM (
                SELECT * FROM real_estate WHERE {w}
                ORDER BY deal_year DESC, deal_month DESC, deal_day DESC
            ) a WHERE ROWNUM <= :maxrow
        ) WHERE rn > :minrow
    """, {**params, 'maxrow': offset + per, 'minrow': offset})

    data = rows_to_list(cur, cur.fetchall())
    cur.close(); conn.close()

    return jsonify({
        'total': total,
        'page': page,
        'per_page': per,
        'pages': (total + per - 1) // per,
        'data': data
    })

@app.route('/api/realestate/stats')
def re_stats():
    prop = request.args.get('prop_type', 'APT')
    region = request.args.get('region', '')

    where = ['prop_type=:prop']
    params = {'prop': prop}
    if region:
        where.append('region=:region')
        params['region'] = region

    w = ' AND '.join(where)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) FROM real_estate WHERE {w}", params)
    total = cur.fetchone()[0]

    cur.execute(f"""
        SELECT deal_type, COUNT(*) cnt, ROUND(AVG(price)) avg_price
        FROM real_estate WHERE {w} AND price > 0
        GROUP BY deal_type
    """, params)
    by_type = rows_to_list(cur, cur.fetchall())

    # 연도별 평균
    cur.execute(f"""
        SELECT deal_year, ROUND(AVG(price)) avg_price, COUNT(*) cnt
        FROM real_estate WHERE {w} AND deal_type='S' AND price > 0
        GROUP BY deal_year ORDER BY deal_year
    """, params)
    yearly = rows_to_list(cur, cur.fetchall())

    cur.close(); conn.close()

    return jsonify({
        'total': total,
        'by_type': by_type,
        'yearly': yearly
    })

# ============================================================
#  /api/posts/* (게시판)
# ============================================================

@app.route('/api/posts', methods=['GET'])
def list_posts():
    """게시글 목록 (페이징, 필터)"""
    page = int(request.args.get('page', 1))
    per = int(request.args.get('per_page', 20))
    post_type = request.args.get('type', '')  # notice / question / 빈값=전체
    search = request.args.get('q', '')

    where = ['1=1']
    params = {}

    if post_type:
        where.append('post_type=:ptype')
        params['ptype'] = post_type
    if search:
        where.append("(UPPER(title) LIKE '%'||UPPER(:q)||'%' OR UPPER(content) LIKE '%'||UPPER(:q)||'%')")
        params['q'] = search

    w = ' AND '.join(where)
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) FROM posts WHERE {w}", params)
    total = cur.fetchone()[0]

    offset = (page - 1) * per
    cur.execute(f"""
        SELECT * FROM (
            SELECT a.*, ROWNUM rn FROM (
                SELECT id, post_type, title, author, content, pinned, views,
                       created_at, updated_at
                FROM posts WHERE {w}
                ORDER BY pinned DESC NULLS LAST, created_at DESC
            ) a WHERE ROWNUM <= :maxrow
        ) WHERE rn > :minrow
    """, {**params, 'maxrow': offset + per, 'minrow': offset})

    posts = rows_to_list(cur, cur.fetchall())

    # 각 글의 댓글 수
    if posts:
        ids = [p['id'] for p in posts]
        placeholders = ','.join([f':cid{i}' for i in range(len(ids))])
        cparams = {f'cid{i}': ids[i] for i in range(len(ids))}
        cur.execute(f"""
            SELECT post_id, COUNT(*) cnt FROM comments
            WHERE post_id IN ({placeholders})
            GROUP BY post_id
        """, cparams)
        ccounts = {r[0]: r[1] for r in cur.fetchall()}
        for p in posts:
            p['comment_count'] = ccounts.get(p['id'], 0)
            p['created_at'] = dt_str(p.get('created_at'))
            p['updated_at'] = dt_str(p.get('updated_at'))

    cur.close(); conn.close()
    return jsonify({
        'total': total,
        'page': page,
        'per_page': per,
        'pages': (total + per - 1) // per,
        'data': posts
    })

@app.route('/api/posts/<int:post_id>', methods=['GET'])
def get_post(post_id):
    """게시글 상세 + 댓글"""
    conn = get_conn()
    cur = conn.cursor()

    # 조회수 증가
    cur.execute("UPDATE posts SET views = NVL(views,0)+1 WHERE id=:id", {'id': post_id})
    conn.commit()

    cur.execute("SELECT * FROM posts WHERE id=:id", {'id': post_id})
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return jsonify({'error': '글을 찾을 수 없습니다.'}), 404

    post = row_to_dict(cur, row)
    post['created_at'] = dt_str(post.get('created_at'))
    post['updated_at'] = dt_str(post.get('updated_at'))
    # pw_hash는 프론트에 노출하지 않음
    post.pop('pw_hash', None)

    # 댓글
    cur.execute("""
        SELECT id, post_id, author, content, is_admin, created_at
        FROM comments WHERE post_id=:pid ORDER BY created_at ASC
    """, {'pid': post_id})
    comments = rows_to_list(cur, cur.fetchall())
    for c in comments:
        c['created_at'] = dt_str(c.get('created_at'))

    post['comments'] = comments
    cur.close(); conn.close()
    return jsonify(post)

@app.route('/api/posts', methods=['POST'])
def create_post():
    """게시글 작성"""
    d = request.get_json()
    if not d:
        return jsonify({'error': 'JSON 필요'}), 400

    title = (d.get('title') or '').strip()
    content = (d.get('content') or '').strip()
    author = (d.get('author') or '').strip() or '익명'
    post_type = d.get('type', 'question')
    pw = d.get('password', '')
    pinned = 1 if d.get('pinned') else 0

    if not title:
        return jsonify({'error': '제목을 입력하세요.'}), 400
    if not content:
        return jsonify({'error': '내용을 입력하세요.'}), 400

    # 공지는 관리자 비번 필요
    pw_hashed = hash_pw(pw) if pw else ''
    if post_type == 'notice':
        if pw_hashed != ADMIN_PW_HASH:
            return jsonify({'error': '관리자 비밀번호가 틀렸습니다.'}), 403
    else:
        if len(pw) < 4:
            return jsonify({'error': '비밀번호를 4자 이상 입력하세요.'}), 400
        pinned = 0  # 문의는 고정 불가

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO posts (post_type, title, author, content, pw_hash, pinned, views, created_at)
        VALUES (:ptype, :title, :author, :content, :pw, :pinned, 0, SYSTIMESTAMP)
        RETURNING id INTO :out_id
    """, {
        'ptype': post_type, 'title': title, 'author': author,
        'content': content, 'pw': pw_hashed, 'pinned': pinned,
        'out_id': cur.var(int)
    })
    new_id = cur.getvalue()[0] if hasattr(cur, 'getvalue') else None
    # oracledb RETURNING 처리
    conn.commit()

    # RETURNING으로 id 가져오기
    if new_id is None:
        cur.execute("SELECT MAX(id) FROM posts")
        new_id = cur.fetchone()[0]

    cur.close(); conn.close()
    return jsonify({'ok': True, 'id': new_id}), 201

@app.route('/api/posts/<int:post_id>', methods=['PUT'])
def update_post(post_id):
    """게시글 수정"""
    d = request.get_json()
    if not d:
        return jsonify({'error': 'JSON 필요'}), 400

    pw = d.get('password', '')
    pw_hashed = hash_pw(pw) if pw else ''

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pw_hash, post_type FROM posts WHERE id=:id", {'id': post_id})
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return jsonify({'error': '글을 찾을 수 없습니다.'}), 404

    stored_hash, stored_type = row
    is_admin = (pw_hashed == ADMIN_PW_HASH)
    is_owner = (pw_hashed == stored_hash)

    if not is_admin and not is_owner:
        cur.close(); conn.close()
        return jsonify({'error': '비밀번호가 틀렸습니다.'}), 403

    title = (d.get('title') or '').strip()
    content = (d.get('content') or '').strip()
    author = (d.get('author') or '').strip() or '익명'
    pinned = 1 if d.get('pinned') else 0

    if not title or not content:
        cur.close(); conn.close()
        return jsonify({'error': '제목과 내용을 입력하세요.'}), 400

    cur.execute("""
        UPDATE posts SET title=:title, author=:author, content=:content,
        pinned=:pinned, updated_at=SYSTIMESTAMP WHERE id=:id
    """, {'title': title, 'author': author, 'content': content,
          'pinned': pinned, 'id': post_id})
    conn.commit()
    cur.close(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
def delete_post(post_id):
    """게시글 삭제"""
    d = request.get_json() or {}
    pw = d.get('password', '')
    pw_hashed = hash_pw(pw) if pw else ''

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pw_hash, post_type FROM posts WHERE id=:id", {'id': post_id})
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return jsonify({'error': '글을 찾을 수 없습니다.'}), 404

    stored_hash, stored_type = row
    is_admin = (pw_hashed == ADMIN_PW_HASH)
    is_owner = (pw_hashed == stored_hash)

    if not is_admin and not is_owner:
        cur.close(); conn.close()
        return jsonify({'error': '비밀번호가 틀렸습니다.'}), 403

    # 댓글도 함께 삭제
    cur.execute("DELETE FROM comments WHERE post_id=:id", {'id': post_id})
    cur.execute("DELETE FROM posts WHERE id=:id", {'id': post_id})
    conn.commit()
    cur.close(); conn.close()
    return jsonify({'ok': True})

# ============================================================
#  /api/comments/* (댓글)
# ============================================================

@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
def add_comment(post_id):
    """댓글 등록"""
    d = request.get_json()
    if not d:
        return jsonify({'error': 'JSON 필요'}), 400

    author = (d.get('author') or '').strip() or '익명'
    content = (d.get('content') or '').strip()

    if not content:
        return jsonify({'error': '댓글 내용을 입력하세요.'}), 400

    # 관리자 이름 체크
    is_admin = 0
    admin_names = ['운영자', '관리자', 'admin']
    if author in admin_names:
        pw = d.get('password', '')
        if hash_pw(pw) != ADMIN_PW_HASH:
            return jsonify({'error': '관리자 비밀번호가 틀렸습니다.'}), 403
        is_admin = 1

    conn = get_conn()
    cur = conn.cursor()

    # 글 존재 확인
    cur.execute("SELECT id FROM posts WHERE id=:id", {'id': post_id})
    if not cur.fetchone():
        cur.close(); conn.close()
        return jsonify({'error': '글을 찾을 수 없습니다.'}), 404

    cur.execute("""
        INSERT INTO comments (post_id, author, content, is_admin, created_at)
        VALUES (:pid, :author, :content, :is_admin, SYSTIMESTAMP)
    """, {'pid': post_id, 'author': author, 'content': content, 'is_admin': is_admin})
    conn.commit()
    cur.close(); conn.close()
    return jsonify({'ok': True}), 201

@app.route('/api/comments/<int:comment_id>', methods=['DELETE'])
def delete_comment(comment_id):
    """댓글 삭제 (관리자만)"""
    d = request.get_json() or {}
    pw = d.get('password', '')
    if hash_pw(pw) != ADMIN_PW_HASH:
        return jsonify({'error': '관리자 비밀번호가 틀렸습니다.'}), 403

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM comments WHERE id=:id", {'id': comment_id})
    conn.commit()
    cur.close(); conn.close()
    return jsonify({'ok': True})

# ============================================================
#  메인
# ============================================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
