#!/usr/bin/env python3
"""DB 스키마 확인+생성 스크립트 — VM에서 실행: python3 ~/swingfarmer.github.io/scripts/check_db_schema.py"""
import os, oracledb

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

W = os.path.expanduser('~/wallet')
conn = oracledb.connect(user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD',''),
    dsn='db1007_medium', config_dir=W, wallet_location=W,
    wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD',''))
cur = conn.cursor()
print("=== DB 연결 성공 ===")

cur.execute("SELECT table_name FROM user_tables ORDER BY table_name")
tables = [r[0] for r in cur.fetchall()]
print(f"테이블: {tables}")

# ── CATEGORIES ──
if 'CATEGORIES' not in tables:
    print("\n[+] CATEGORIES 생성...")
    cur.execute("""CREATE TABLE categories (
        id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name VARCHAR2(40) NOT NULL,
        sort_order NUMBER DEFAULT 0,
        created_at TIMESTAMP DEFAULT SYSTIMESTAMP
    )""")
    conn.commit()
    print("  → 완료")
else:
    cur.execute("SELECT COUNT(*) FROM categories"); print(f"\nCATEGORIES: {cur.fetchone()[0]}건")

# ── POSTS ──
if 'POSTS' not in tables:
    print("\n[+] POSTS 생성...")
    cur.execute("""CREATE TABLE posts (
        id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        category VARCHAR2(40) DEFAULT '',
        title VARCHAR2(200) NOT NULL,
        author VARCHAR2(50) DEFAULT '익명',
        content CLOB,
        pw_hash VARCHAR2(64),
        pinned NUMBER(1) DEFAULT 0,
        views NUMBER DEFAULT 0,
        created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
        updated_at TIMESTAMP
    )""")
    cur.execute("CREATE INDEX idx_posts_cat ON posts(category)")
    cur.execute("CREATE INDEX idx_posts_created ON posts(created_at DESC)")
    conn.commit()
    print("  → 완료")
else:
    cur.execute("SELECT column_name FROM user_tab_columns WHERE table_name='POSTS'")
    cols = [r[0] for r in cur.fetchall()]
    print(f"\nPOSTS 컬럼: {cols}")
    # post_type → category 마이그레이션
    if 'POST_TYPE' in cols and 'CATEGORY' not in cols:
        print("[~] POST_TYPE → CATEGORY 리네임...")
        cur.execute("ALTER TABLE posts RENAME COLUMN post_type TO category")
        conn.commit(); print("  → 완료")
    elif 'CATEGORY' not in cols and 'POST_TYPE' not in cols:
        print("[+] CATEGORY 컬럼 추가...")
        cur.execute("ALTER TABLE posts ADD category VARCHAR2(40) DEFAULT ''")
        conn.commit(); print("  → 완료")
    elif 'CATEGORY' in cols:
        print("  CATEGORY 컬럼 이미 존재")
    cur.execute("SELECT COUNT(*) FROM posts"); print(f"  POSTS: {cur.fetchone()[0]}건")

# ── COMMENTS ──
if 'COMMENTS' not in tables:
    print("\n[+] COMMENTS 생성...")
    cur.execute("""CREATE TABLE comments (
        id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        post_id NUMBER NOT NULL,
        author VARCHAR2(50) DEFAULT '익명',
        content VARCHAR2(2000),
        is_admin NUMBER(1) DEFAULT 0,
        created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
        CONSTRAINT fk_comments_post FOREIGN KEY (post_id) REFERENCES posts(id)
    )""")
    cur.execute("CREATE INDEX idx_comments_post ON comments(post_id)")
    conn.commit()
    print("  → 완료")
else:
    cur.execute("SELECT COUNT(*) FROM comments"); print(f"\nCOMMENTS: {cur.fetchone()[0]}건")

# ── ATTACHMENTS ──
if 'ATTACHMENTS' not in tables:
    print("\n[i] ATTACHMENTS 미생성 (Phase 2에서 생성 예정)")
else:
    cur.execute("SELECT COUNT(*) FROM attachments"); print(f"\nATTACHMENTS: {cur.fetchone()[0]}건")

# 전체 확인
for tbl in ['CATEGORIES','POSTS','COMMENTS']:
    if tbl in tables or tbl == 'CATEGORIES':
        try:
            cur.execute(f"SELECT column_name, data_type FROM user_tab_columns WHERE table_name='{tbl}' ORDER BY column_id")
            print(f"\n--- {tbl} ---")
            for c in cur.fetchall(): print(f"  {c[0]:20s} {c[1]}")
        except: pass

print("\n=== 완료 ===")
cur.close(); conn.close()
