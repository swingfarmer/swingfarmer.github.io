#!/usr/bin/env python3
"""BOARD_POSTS 테이블 + BOARD_REPLIES 테이블 생성 (Oracle Autonomous)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from api_server import get_conn

def migrate():
    conn = get_conn()
    cur = conn.cursor()

    # BOARD_POSTS
    cur.execute("""
        SELECT COUNT(*) FROM user_tables WHERE table_name='BOARD_POSTS'
    """)
    if cur.fetchone()[0] == 0:
        cur.execute("""
            CREATE TABLE board_posts (
                id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                post_type   VARCHAR2(20) DEFAULT 'question',
                title       VARCHAR2(200) NOT NULL,
                author      VARCHAR2(50) DEFAULT '익명',
                content     CLOB,
                pw_hash     VARCHAR2(64),
                is_pinned   NUMBER(1) DEFAULT 0,
                views       NUMBER DEFAULT 0,
                created_at  TIMESTAMP DEFAULT SYSTIMESTAMP,
                updated_at  TIMESTAMP
            )
        """)
        print("✓ BOARD_POSTS 테이블 생성")
    else:
        print("· BOARD_POSTS 이미 존재")

    # BOARD_REPLIES
    cur.execute("""
        SELECT COUNT(*) FROM user_tables WHERE table_name='BOARD_REPLIES'
    """)
    if cur.fetchone()[0] == 0:
        cur.execute("""
            CREATE TABLE board_replies (
                id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                post_id     NUMBER NOT NULL REFERENCES board_posts(id) ON DELETE CASCADE,
                author      VARCHAR2(50) DEFAULT '익명',
                content     VARCHAR2(1000),
                created_at  TIMESTAMP DEFAULT SYSTIMESTAMP
            )
        """)
        print("✓ BOARD_REPLIES 테이블 생성")
    else:
        print("· BOARD_REPLIES 이미 존재")

    conn.commit()
    cur.close()
    conn.close()
    print("완료!")

if __name__ == '__main__':
    migrate()
