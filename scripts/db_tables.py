#!/usr/bin/env python3
"""
Oracle DB 테이블 점검·백업·삭제·복구 도구
==========================================
VM에서 실행 (먼저 . ~/.env_secrets):

  python3 scripts/db_tables.py                     # 전체 테이블 + 행 수 목록 (읽기만)
  python3 scripts/db_tables.py --backup T1 T2      # 테이블 구조(DDL) + 데이터(JSON)를 ~/db_backup/ 에 저장
  python3 scripts/db_tables.py --drop T1 T2        # 삭제. 백업 파일이 있어야 하고, y 입력해야 실행
  python3 scripts/db_tables.py --recyclebin        # 휴지통(삭제된 테이블) 목록
  python3 scripts/db_tables.py --restore T1        # 휴지통에서 되살리기 (FLASHBACK)

삭제는 PURGE 없이 하므로 Oracle 휴지통에 들어감 → --restore 로 되살림.
휴지통에서도 사라졌으면 ~/db_backup/ 의 .sql 로 구조를 다시 만들 수 있음.
"""
import os, sys, json, re
from datetime import datetime, date
from decimal import Decimal


def load_env():
    f = os.path.expanduser('~/.env_secrets')
    if os.path.exists(f):
        for line in open(f):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:]
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
BACKUP_DIR = os.path.expanduser('~/db_backup')
NAME_RE = re.compile(r'^[A-Z][A-Z0-9_$#]{0,127}$')


def connect():
    import oracledb
    w = os.path.expanduser('~/wallet')
    return oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=w, wallet_location=w,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))


def table_names(cur):
    cur.execute("SELECT table_name FROM user_tables ORDER BY table_name")
    return [r[0] for r in cur.fetchall()]


def check_names(cur, names):
    """이름 형식 확인 + 실제로 있는 테이블인지 확인. 대문자로 바꿔서 반환."""
    names = [n.upper() for n in names]
    for n in names:
        if not NAME_RE.match(n):
            sys.exit(f"❌ 테이블 이름 형식이 이상함: {n}")
    exist = set(table_names(cur))
    missing = [n for n in names if n not in exist]
    if missing:
        sys.exit(f"❌ 없는 테이블: {', '.join(missing)}")
    return names


def count_rows(cur, t):
    cur.execute(f'SELECT COUNT(*) FROM "{t}"')
    return cur.fetchone()[0]


def cmd_list(cur):
    names = table_names(cur)
    print(f"=== 테이블 {len(names)}개 ===")
    for t in names:
        try:
            n = count_rows(cur, t)
            print(f"  {t:<30} {n:>12,}행")
        except Exception as e:
            print(f"  {t:<30} (조회 실패: {str(e)[:60]})")


def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return str(o)
    if hasattr(o, 'read'):  # LOB
        return o.read()
    return str(o)


def backup_paths(t):
    return (os.path.join(BACKUP_DIR, f"{t}.sql"), os.path.join(BACKUP_DIR, f"{t}.json"))


def cmd_backup(cur, names):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    for t in names:
        sql_path, json_path = backup_paths(t)
        cur.execute("SELECT DBMS_METADATA.GET_DDL('TABLE', :t) FROM dual", {'t': t})
        ddl = cur.fetchone()[0]
        ddl = ddl.read() if hasattr(ddl, 'read') else ddl
        with open(sql_path, 'w', encoding='utf-8') as f:
            f.write(f"-- {t} 구조 백업 {datetime.now():%Y-%m-%d %H:%M}\n{ddl.strip()}\n")
        cur.execute(f'SELECT * FROM "{t}"')
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({'table': t, 'columns': cols, 'rows': rows}, f,
                      ensure_ascii=False, default=_json_default, indent=1)
        print(f"✅ {t}: 구조 → {sql_path}")
        print(f"   {t}: 데이터 {len(rows):,}행 → {json_path}")


def cmd_drop(conn, cur, names):
    for t in names:
        sql_path, json_path = backup_paths(t)
        if not (os.path.exists(sql_path) and os.path.exists(json_path)):
            sys.exit(f"❌ {t} 백업이 없음. 먼저: python3 scripts/db_tables.py --backup {t}")
    print("삭제 대상:")
    for t in names:
        print(f"  {t}  ({count_rows(cur, t):,}행)")
    ans = input("정말 삭제? 휴지통으로 감 (y 입력): ").strip().lower()
    if ans != 'y':
        print("취소함")
        return
    for t in names:
        # 다른 테이블이 이 테이블을 참조하면 실패함 → 참조하는 쪽을 먼저 지우게 이름 순서대로 시도
        cur.execute(f'DROP TABLE "{t}"')
        print(f"🗑️  {t} 삭제 (휴지통)")
    conn.commit()
    cmd_recyclebin(cur)


def cmd_recyclebin(cur):
    cur.execute("""SELECT original_name, object_name, droptime FROM user_recyclebin
                   WHERE type='TABLE' ORDER BY droptime DESC""")
    rows = cur.fetchall()
    print(f"=== 휴지통 테이블 {len(rows)}개 ===")
    for r in rows:
        print(f"  {r[0]:<30} 삭제시각 {r[2]}")
    if not rows:
        print("  (비어 있음 — 되살리려면 ~/db_backup/ 의 .sql 사용)")


def cmd_restore(conn, cur, name):
    t = name.upper()
    if not NAME_RE.match(t):
        sys.exit(f"❌ 테이블 이름 형식이 이상함: {t}")
    cur.execute("SELECT COUNT(*) FROM user_recyclebin WHERE type='TABLE' AND original_name=:t", {'t': t})
    if cur.fetchone()[0] == 0:
        sys.exit(f"❌ 휴지통에 {t} 없음. ~/db_backup/{t}.sql 로 구조를 다시 만들어야 함")
    cur.execute(f'FLASHBACK TABLE "{t}" TO BEFORE DROP')
    conn.commit()
    print(f"✅ {t} 되살림 ({count_rows(cur, t):,}행)")


def main():
    a = sys.argv[1:]
    conn = connect()
    cur = conn.cursor()
    if not a:
        cmd_list(cur)
    elif a[0] == '--backup' and len(a) > 1:
        cmd_backup(cur, check_names(cur, a[1:]))
    elif a[0] == '--drop' and len(a) > 1:
        cmd_drop(conn, cur, check_names(cur, a[1:]))
    elif a[0] == '--recyclebin':
        cmd_recyclebin(cur)
    elif a[0] == '--restore' and len(a) == 2:
        cmd_restore(conn, cur, a[1])
    else:
        print(__doc__)
    conn.close()


if __name__ == '__main__':
    main()
