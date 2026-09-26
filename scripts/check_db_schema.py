#!/usr/bin/env python3
"""
DB 스키마 확인 스크립트
- posts / comments 테이블 컬럼 확인
- 없으면 생성, 있으면 컬럼 출력
VM에서 실행: python3 ~/swingfarmer.github.io/scripts/check_db_schema.py
"""
import os, sys
import oracledb

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

WALLET_DIR = os.path.expanduser('~/wallet')
conn = oracledb.connect(
    user='ADMIN',
    password=os.environ.get('ORACLE_DB_PASSWORD', ''),
    dsn='db1007_medium',
    config_dir=WALLET_DIR,
    wallet_location=WALLET_DIR,
    wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', '')
)
cur = conn.cursor()

print("=== DB 연결 성공 ===")

# 테이블 목록
cur.execute("SELECT table_name FROM user_tables ORDER BY table_name")
tables = [r[0] for r in cur.fetchall()]
print(f"\n테이블: {tables}")

for tbl in ['POSTS', 'COMMENTS', 'ATTACHMENTS']:
    if tbl in tables:
        cur.execute(f"SELECT column_name, data_type, data_length, nullable FROM user_tab_columns WHERE table_name='{tbl}' ORDER BY column_id")
        cols = cur.fetchall()
        print(f"\n--- {tbl} ---")
        for c in cols:
            print(f"  {c[0]:20s} {c[1]:15s} ({c[2]}) {'NULL' if c[3]=='Y' else 'NOT NULL'}")
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        cnt = cur.fetchone()[0]
        print(f"  → {cnt}건")
    else:
        print(f"\n--- {tbl}: 존재하지 않음 ---")

# posts 테이블이 없으면 생성
if 'POSTS' not in tables:
    print("\n[!] POSTS 테이블 생성 중...")
    cur.execute("""
        CREATE TABLE posts (
            id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            post_type   VARCHAR2(20) DEFAULT 'question',
            title       VARCHAR2(200) NOT NULL,
            author      VARCHAR2(50) DEFAULT '익명',
            content     CLOB,
            pw_hash     VARCHAR2(64),
            pinned      NUMBER(1) DEFAULT 0,
            views       NUMBER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT SYSTIMESTAMP,
            updated_at  TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX idx_posts_type ON posts(post_type)")
    cur.execute("CREATE INDEX idx_posts_created ON posts(created_at DESC)")
    conn.commit()
    print("  → POSTS 생성 완료")

# comments 테이블이 없으면 생성
if 'COMMENTS' not in tables:
    print("\n[!] COMMENTS 테이블 생성 중...")
    cur.execute("""
        CREATE TABLE comments (
            id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            post_id     NUMBER NOT NULL,
            author      VARCHAR2(50) DEFAULT '익명',
            content     VARCHAR2(2000),
            is_admin    NUMBER(1) DEFAULT 0,
            created_at  TIMESTAMP DEFAULT SYSTIMESTAMP,
            CONSTRAINT fk_comments_post FOREIGN KEY (post_id) REFERENCES posts(id)
        )
    """)
    cur.execute("CREATE INDEX idx_comments_post ON comments(post_id)")
    conn.commit()
    print("  → COMMENTS 생성 완료")

# posts에 post_type 컬럼 없으면 (기존에 type으로 만들었을 수 있음)
if 'POSTS' in tables:
    cur.execute("SELECT column_name FROM user_tab_columns WHERE table_name='POSTS'")
    cols = [r[0] for r in cur.fetchall()]
    if 'POST_TYPE' not in cols and 'TYPE' in cols:
        print("\n[!] POSTS.TYPE → POST_TYPE 리네임 중...")
        cur.execute("ALTER TABLE posts RENAME COLUMN \"TYPE\" TO post_type")
        conn.commit()
        print("  → 리네임 완료")
    elif 'POST_TYPE' not in cols and 'TYPE' not in cols:
        print("\n[!] POSTS.POST_TYPE 컬럼 추가 중...")
        cur.execute("ALTER TABLE posts ADD post_type VARCHAR2(20) DEFAULT 'question'")
        conn.commit()
        print("  → 추가 완료")

print("\n=== 완료 ===")
cur.close()
conn.close()
