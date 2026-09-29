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

# ── NOTE_CATEGORIES ──
if 'NOTE_CATEGORIES' not in tables:
    print("\n[+] NOTE_CATEGORIES 생성...")
    cur.execute("""CREATE TABLE note_categories (
        id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name VARCHAR2(40) NOT NULL,
        sort_order NUMBER DEFAULT 0,
        created_at TIMESTAMP DEFAULT SYSTIMESTAMP
    )""")
    # 기본 카테고리 삽입
    for i, name in enumerate(['메모', '시장관찰', '종목분석', '매매기록'], 1):
        cur.execute("INSERT INTO note_categories (name, sort_order) VALUES (:n, :s)", {'n': name, 's': i})
    conn.commit()
    print("  → 완료 (기본 4개 카테고리 삽입)")
else:
    cur.execute("SELECT COUNT(*) FROM note_categories"); print(f"\nNOTE_CATEGORIES: {cur.fetchone()[0]}건")

# ── NOTES ──
if 'NOTES' not in tables:
    print("\n[+] NOTES 생성...")
    cur.execute("""CREATE TABLE notes (
        id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        category VARCHAR2(40) DEFAULT '',
        title VARCHAR2(200),
        content CLOB,
        author VARCHAR2(50) DEFAULT '스윙파머',
        is_pinned NUMBER(1) DEFAULT 0,
        views NUMBER DEFAULT 0,
        created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
        updated_at TIMESTAMP
    )""")
    cur.execute("CREATE INDEX idx_notes_cat ON notes(category)")
    cur.execute("CREATE INDEX idx_notes_created ON notes(created_at DESC)")
    conn.commit()
    print("  → 완료")
else:
    cur.execute("SELECT COUNT(*) FROM notes"); print(f"\nNOTES: {cur.fetchone()[0]}건")

# ── EXCHANGE_RATES ──
if 'EXCHANGE_RATES' not in tables:
    print("\n[+] EXCHANGE_RATES 생성...")
    cur.execute("""CREATE TABLE exchange_rates (
        id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        rate_date DATE NOT NULL,
        cur_unit VARCHAR2(10) NOT NULL,
        cur_nm VARCHAR2(40),
        ttb NUMBER(18,4),
        tts NUMBER(18,4),
        deal_bas_r NUMBER(18,4),
        bkpr NUMBER(18,4),
        yy_efee_r NUMBER(10,4),
        ten_dd_efee_r NUMBER(10,4),
        kftc_deal_bas_r NUMBER(18,4),
        kftc_bkpr NUMBER(18,4),
        created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
        CONSTRAINT uq_exrate UNIQUE (rate_date, cur_unit)
    )""")
    cur.execute("CREATE INDEX idx_exrate_date ON exchange_rates(rate_date DESC)")
    cur.execute("CREATE INDEX idx_exrate_cur ON exchange_rates(cur_unit)")
    conn.commit()
    print("  → 완료")
else:
    cur.execute("SELECT COUNT(*) FROM exchange_rates"); print(f"\nEXCHANGE_RATES: {cur.fetchone()[0]}건")

# ── INTEREST_RATES ──
if 'INTEREST_RATES' not in tables:
    print("\n[+] INTEREST_RATES 생성...")
    cur.execute("""CREATE TABLE interest_rates (
        id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        rate_date DATE NOT NULL,
        data_type VARCHAR2(10) NOT NULL,
        item_code VARCHAR2(20),
        item_nm VARCHAR2(80),
        rate NUMBER(10,4),
        created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
        CONSTRAINT uq_intrate UNIQUE (rate_date, data_type, item_code)
    )""")
    cur.execute("CREATE INDEX idx_intrate_date ON interest_rates(rate_date DESC)")
    cur.execute("CREATE INDEX idx_intrate_type ON interest_rates(data_type)")
    conn.commit()
    print("  → 완료")
else:
    cur.execute("SELECT COUNT(*) FROM interest_rates"); print(f"\nINTEREST_RATES: {cur.fetchone()[0]}건")

# ── GOLD_PRICES ──
if 'GOLD_PRICES' not in tables:
    print("\n[+] GOLD_PRICES 생성...")
    cur.execute("""CREATE TABLE gold_prices (
        id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        price_date DATE NOT NULL,
        price_usd NUMBER(12,2),
        price_krw_g NUMBER(12,0),
        usd_krw NUMBER(12,4),
        source VARCHAR2(20) DEFAULT 'yfinance',
        created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
        CONSTRAINT uq_gold_date UNIQUE (price_date)
    )""")
    cur.execute("CREATE INDEX idx_gold_date ON gold_prices(price_date DESC)")
    conn.commit()
    print("  → 완료")
else:
    cur.execute("SELECT COUNT(*) FROM gold_prices"); print(f"\nGOLD_PRICES: {cur.fetchone()[0]}건")

# 전체 확인
for tbl in ['CATEGORIES','POSTS','COMMENTS','NOTE_CATEGORIES','NOTES','EXCHANGE_RATES','INTEREST_RATES','GOLD_PRICES']:
    if tbl in tables or tbl == 'CATEGORIES':
        try:
            cur.execute(f"SELECT column_name, data_type FROM user_tab_columns WHERE table_name='{tbl}' ORDER BY column_id")
            print(f"\n--- {tbl} ---")
            for c in cur.fetchall(): print(f"  {c[0]:20s} {c[1]}")
        except: pass

print("\n=== 완료 ===")
cur.close(); conn.close()
