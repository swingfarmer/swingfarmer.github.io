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
  python3 scripts/db_tables.py --space             # (116) 용량 점검 — 테이블·인덱스·LOB·휴지통이 차지하는 MB (읽기만)
  python3 scripts/db_tables.py --shrink-plan       # (117) 부푼 테이블 찾기 + DATA 공간 줄이기 미리보기 (읽기만)
  python3 scripts/db_tables.py --shrink T1 T2      # (117) 테이블 빈칸 압축(행은 그대로). 백업 있어야 하고 y 입력
  python3 scripts/db_tables.py --move T1 T2        # (117) --shrink가 안 줄면: 테이블을 새로 촘촘히 다시 씀(MOVE ONLINE, 행·인덱스 그대로). 백업·y 필수
  python3 scripts/db_tables.py --shrink-ts         # (117) DATA 공간 파일 자체를 줄임(무료 한도 계산이 줄어듦). y 입력

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


def cmd_space(cur):
    """(116) ORA-65114(저장 공간 초과) 원인 찾기 — 읽기만
    (117) 무료 한도는 「SAMPLESCHEMA 뺀 데이터 파일 할당 크기」로 셈(dba_data_files) — 지운 뒤에도 파일은 안 줄어듦.
          그래서 맨 위에 그 숫자 + 공간별 할당/빈칸, 아래에 큰 테이블의 행 수·실제 데이터 추정(부풀었는지)"""
    def q(sql, *a):
        try:
            cur.execute(sql, *a); return cur.fetchall()
        except Exception as e:
            print('  (못 읽음:', str(e).split(chr(10))[0], ')'); return None
    r = q("SELECT banner_full FROM v$version")
    if r: print('DB 버전:', ' / '.join(x[0].replace(chr(10), ' ') for x in r)[:160])
    r = q("SELECT property_value FROM database_properties WHERE property_name='MAX_PDB_STORAGE'")
    if r: print('MAX_PDB_STORAGE:', r[0][0])
    r = q("""SELECT f.tablespace_name, ROUND(SUM(f.bytes)/1048576),
                    ROUND(NVL(MAX(fs.free),0)/1048576), MAX(f.autoextensible), ROUND(MAX(f.maxbytes)/1048576)
             FROM dba_data_files f
             LEFT JOIN (SELECT tablespace_name, SUM(bytes) free FROM dba_free_space GROUP BY tablespace_name) fs
               ON fs.tablespace_name = f.tablespace_name
             GROUP BY f.tablespace_name ORDER BY 2 DESC""")
    if r:
        tot = sum(x[1] for x in r if x[0] != 'SAMPLESCHEMA')
        print(f"=== ★ 한도 계산용: 데이터 파일 할당 합계(SAMPLESCHEMA 제외) {tot:,} MB / 20,480 MB = {tot/20480*100:.0f}% ===")
        print("  공간 / 할당 MB / 그중 빈칸 MB / 자동확장 / 최대 MB")
        for t, mb, fr, ae, mx in r:
            print(f"  {t:<20} {mb:>9,} {fr:>9,} {ae:>4} {mx:>10,}")
    r = q("SELECT tablespace_name, ROUND(SUM(bytes)/1048576) FROM dba_temp_files GROUP BY tablespace_name")
    if r:
        for t, mb in r: print(f"  (임시) {t:<14} {mb:>9,} MB")
    print("=== 큰 테이블: 행 수 · 실제 데이터 추정(행 수×평균 길이) · 조각 크기 ===")
    r = q("""SELECT t.table_name, t.num_rows, t.avg_row_len, t.blocks, t.compression, t.compress_for,
                    TO_CHAR(t.last_analyzed,'YYYY-MM-DD'), t.partitioned, ROUND(s.mb,1)
             FROM user_tables t
             JOIN (SELECT segment_name, SUM(bytes)/1048576 mb FROM user_segments
                   WHERE segment_type LIKE 'TABLE%' GROUP BY segment_name) s ON s.segment_name = t.table_name
             ORDER BY s.mb DESC FETCH FIRST 8 ROWS ONLY""")
    if r:
        for tn, nr, arl, bl, cp, cf, la, pt, mb in r:
            est = (nr or 0) * (arl or 0) / 1048576
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{tn}"'); live = cur.fetchone()[0]
            except Exception:
                live = None
            lv = f"{live:,}" if live is not None else '?'
            print(f"  {tn:<18} 조각 {mb:>8,.1f}MB | 지금 행 {lv:>10} | 통계 행 {nr or 0:>10,} × 평균 {arl or 0}B ≈ {est:,.1f}MB"
                  f" | 압축 {cp}/{cf or '-'} | 분할 {pt} | 통계일 {la}")
    try:
        cur.execute("SELECT ROUND(SUM(bytes)/1048576) FROM dba_segments")
        print(f"=== DB 전체 사용(모든 계정·시스템 포함) {cur.fetchone()[0]:,} MB (무료 한도 약 20,480 MB) ===")
    except Exception as e:
        print('  (dba_segments 못 읽음:', str(e).split(chr(10))[0], ')')
    try:
        cur.execute("""SELECT tablespace_name, ROUND(SUM(bytes)/1048576) FROM dba_segments
                       GROUP BY tablespace_name ORDER BY 2 DESC""")
        for t, mb in cur.fetchall(): print(f"  공간 {t:<20} {mb:>8,} MB")
    except Exception:
        pass
    cur.execute("SELECT ROUND(SUM(bytes)/1048576) FROM user_segments")
    print(f"=== 내 계정(ADMIN) 합계 {cur.fetchone()[0]:,} MB ===")
    cur.execute("""SELECT s.segment_type, NVL(l.table_name, NVL(i.table_name, s.segment_name)), s.segment_name, ROUND(s.bytes/1048576,1)
                   FROM user_segments s
                   LEFT JOIN user_lobs l ON l.segment_name = s.segment_name
                   LEFT JOIN user_indexes i ON i.index_name = s.segment_name
                   ORDER BY s.bytes DESC FETCH FIRST 20 ROWS ONLY""")
    print("  상위 20 (종류 / 테이블 / 조각 이름 / MB)")
    for typ, tb, seg, mb in cur.fetchall():
        print(f"  {typ:<16} {tb:<30} {seg[:28]:<28} {mb:>9,.1f}")
    cur.execute("SELECT COUNT(*), ROUND(NVL(SUM(space),0)*8192/1048576) FROM user_recyclebin")
    n, mb = cur.fetchone()
    print(f"=== 휴지통 {n}개 · 약 {mb:,} MB (블록 8KB 가정) ===")


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


# ---------- (117) ORA-65114 정리: 부푼 테이블 압축 → DATA 공간 파일 줄이기 ----------
def _alloc(cur):
    """SAMPLESCHEMA 뺀 데이터 파일 할당 합계 MB(무료 한도 계산), DATA 할당·빈칸"""
    cur.execute("SELECT ROUND(SUM(bytes)/1048576) FROM dba_data_files WHERE tablespace_name <> 'SAMPLESCHEMA'")
    tot = cur.fetchone()[0]
    cur.execute("SELECT ROUND(SUM(bytes)/1048576) FROM dba_data_files WHERE tablespace_name='DATA'")
    d = cur.fetchone()[0]
    cur.execute("SELECT ROUND(NVL(SUM(bytes),0)/1048576) FROM dba_free_space WHERE tablespace_name='DATA'")
    fr = cur.fetchone()[0]
    return tot, d, fr


def _print_alloc(cur, title):
    tot, d, fr = _alloc(cur)
    print(f"=== {title}: 한도 계산 {tot:,} MB / 20,480 MB = {tot/20480*100:.0f}% | DATA 할당 {d:,} MB (빈칸 {fr:,} MB) ===")


def _seg_mb(cur, t):
    cur.execute("SELECT ROUND(NVL(SUM(bytes),0)/1048576,1) FROM user_segments WHERE segment_name=:t", {'t': t})
    tb = cur.fetchone()[0]
    cur.execute("""SELECT ROUND(NVL(SUM(s.bytes),0)/1048576,1) FROM user_segments s
                   JOIN user_indexes i ON i.index_name=s.segment_name WHERE i.table_name=:t""", {'t': t})
    return tb, cur.fetchone()[0]


def _bloated(cur):
    """조각 10MB 넘고 실제 데이터 추정의 5배 넘는 테이블"""
    cur.execute("""SELECT t.table_name, ROUND(s.mb,1), ROUND(NVL(t.num_rows,0)*NVL(t.avg_row_len,0)/1048576,1),
                          s.ext, ROUND(s.ini/1024), ROUND(NVL(s.nxt,0)/1024)
                   FROM user_tables t
                   JOIN (SELECT segment_name, SUM(bytes)/1048576 mb, SUM(extents) ext,
                                MAX(initial_extent) ini, MAX(next_extent) nxt
                         FROM user_segments WHERE segment_type='TABLE' GROUP BY segment_name) s
                     ON s.segment_name=t.table_name
                   WHERE s.mb > 10 ORDER BY s.mb DESC""")
    return [r for r in cur.fetchall() if r[1] > 5 * max(r[2], 0.1)]


def _ts_shrink(cur, mode_name):
    import oracledb
    res = cur.var(oracledb.DB_TYPE_CLOB)
    cur.execute(f"""BEGIN DBMS_SPACE.SHRINK_TABLESPACE(ts_name => 'DATA',
                      shrink_mode => DBMS_SPACE.{mode_name}, shrink_result => :r); END;""", r=res)
    v = res.getvalue()
    return (v.read() if hasattr(v, 'read') else v) or ''


def cmd_shrink_plan(cur):
    _print_alloc(cur, '지금')
    rows = _bloated(cur)
    print(f"=== 부푼 테이블 {len(rows)}개 (조각 MB / 실제 데이터 추정 MB / 조각 수 / 첫 조각 KB / 다음 조각 KB) ===")
    for t, mb, est, ext, ini, nxt in rows:
        print(f"  {t:<18} {mb:>9,.1f} {est:>8,.1f} {ext:>7,} {ini:>9,} {nxt:>9,}")
    if rows:
        print("  → 압축 대상: " + ' '.join(r[0] for r in rows))
    print("=== DATA 공간 줄이기 미리보기 (DBMS_SPACE 분석 모드 — 아무것도 안 바꿈) ===")
    try:
        print(_ts_shrink(cur, 'TS_MODE_ANALYZE').strip()[:3000])
    except Exception as e:
        print('  ❌ 미리보기 실패:', str(e).split(chr(10))[0])


def cmd_shrink(conn, cur, names):
    for t in names:
        sql_path, json_path = backup_paths(t)
        if not (os.path.exists(sql_path) and os.path.exists(json_path)):
            sys.exit(f"❌ {t} 백업이 없음. 먼저: python3 scripts/db_tables.py --backup {t}")
    _print_alloc(cur, '압축 전')
    print("압축 대상 (행은 안 지움 — 테이블 안 빈칸만 모음, 1~2분에 끝날 것):")
    before = {}
    for t in names:
        before[t] = (count_rows(cur, t),) + _seg_mb(cur, t)
        print(f"  {t:<18} {before[t][0]:>10,}행  테이블 {before[t][1]:,} MB  인덱스 {before[t][2]:,} MB")
    if input("압축할까? (y 입력): ").strip().lower() != 'y':
        print("취소함"); return
    bad = 0
    for t in names:
        try:
            cur.execute(f'ALTER TABLE "{t}" ENABLE ROW MOVEMENT')
            cur.execute(f'ALTER TABLE "{t}" SHRINK SPACE CASCADE')
            n, tb, ix = (count_rows(cur, t),) + _seg_mb(cur, t)
            ok = '✅' if n == before[t][0] else '❌ 행 수 다름!'
            if n != before[t][0]: bad += 1
            print(f"{ok} {t:<18} {n:,}행 | 테이블 {before[t][1]:,} → {tb:,} MB | 인덱스 {before[t][2]:,} → {ix:,} MB")
        except Exception as e:
            bad += 1
            print(f"❌ {t}: {str(e).split(chr(10))[0]}")
    _print_alloc(cur, '압축 후')
    print("※ 테이블을 줄여도 DATA 파일 크기(한도 계산)는 그대로 — 다음 단계 --shrink-ts 가 파일을 줄임" if not bad else "※ 실패가 있음 — 화면 그대로 붙여 줄 것")


def cmd_move(conn, cur, names):
    """(117) SHRINK SPACE가 0 MB 줄어서(117 실측) MOVE ONLINE으로 다시 씀 — 같은 DATA 안 빈칸으로 옮겨 파일은 안 커짐"""
    for t in names:
        sql_path, json_path = backup_paths(t)
        if not (os.path.exists(sql_path) and os.path.exists(json_path)):
            sys.exit(f"❌ {t} 백업이 없음. 먼저: python3 scripts/db_tables.py --backup {t}")
    # 원인 단서: 첫 테이블 구조에서 저장 관련 줄만
    try:
        cur.execute("SELECT DBMS_METADATA.GET_DDL('TABLE', :t) FROM dual", {'t': names[0]})
        ddl = cur.fetchone()[0]; ddl = ddl.read() if hasattr(ddl, 'read') else ddl
        keep = [l.strip() for l in ddl.splitlines()
                if re.search(r'STORAGE|INITIAL|PCTFREE|COMPRESS|MEMOPTIMIZE|LOGGING|SEGMENT|INMEMORY|ORGANIZATION', l)]
        print(f"[구조 단서 {names[0]}] " + ' / '.join(keep)[:600])
    except Exception as e:
        print('  (구조 못 읽음:', str(e).split(chr(10))[0], ')')
    _print_alloc(cur, '다시 쓰기 전')
    before = {}
    for t in names:
        before[t] = (count_rows(cur, t),) + _seg_mb(cur, t)
        print(f"  {t:<18} {before[t][0]:>10,}행  테이블 {before[t][1]:,} MB  인덱스 {before[t][2]:,} MB")
    if input("다시 쓸까? (y 입력): ").strip().lower() != 'y':
        print("취소함"); return
    bad = 0
    for t in names:
        try:
            cur.execute(f'ALTER TABLE "{t}" MOVE ONLINE')
            n, tb, ix = (count_rows(cur, t),) + _seg_mb(cur, t)
            cur.execute("SELECT COUNT(*) FROM user_indexes WHERE table_name=:t AND status NOT IN ('VALID','N/A')", {'t': t})
            inval = cur.fetchone()[0]
            ok = n == before[t][0] and inval == 0
            if not ok: bad += 1
            print(f"{'✅' if ok else '❌'} {t:<18} {n:,}행 | 테이블 {before[t][1]:,} → {tb:,} MB | 인덱스 {before[t][2]:,} → {ix:,} MB"
                  + (f" | ❌ 망가진 인덱스 {inval}개" if inval else '') + ('' if n == before[t][0] else ' | ❌ 행 수 다름!'))
        except Exception as e:
            bad += 1
            print(f"❌ {t}: {str(e).split(chr(10))[0]}")
    _print_alloc(cur, '다시 쓴 후')
    print("※ 실패가 있음 — 화면 그대로 붙여 줄 것" if bad else "※ 다음: --shrink-plan 으로 줄일 크기 다시 확인 → --shrink-ts")


def cmd_shrink_ts(cur):
    _print_alloc(cur, '줄이기 전')
    print("DATA 공간 파일을 쓰는 만큼만 남기고 줄임 (데이터는 안 지움. 오라클이 조각을 앞쪽으로 옮긴 뒤 파일 끝을 잘라냄)")
    if input("진행할까? (y 입력): ").strip().lower() != 'y':
        print("취소함"); return
    try:
        out = _ts_shrink(cur, 'TS_MODE_SHRINK')
        print(out.strip()[:3000])
    except Exception as e:
        print('❌ 실패:', str(e).split(chr(10))[0])
    _print_alloc(cur, '줄이기 후')


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
    elif a[0] == '--space':
        cmd_space(cur)
    elif a[0] == '--shrink-plan':
        cmd_shrink_plan(cur)
    elif a[0] == '--shrink' and len(a) > 1:
        cmd_shrink(conn, cur, check_names(cur, a[1:]))
    elif a[0] == '--move' and len(a) > 1:
        cmd_move(conn, cur, check_names(cur, a[1:]))
    elif a[0] == '--shrink-ts':
        cmd_shrink_ts(cur)
    elif a[0] == '--restore' and len(a) == 2:
        cmd_restore(conn, cur, a[1])
    else:
        print(__doc__)
    conn.close()


if __name__ == '__main__':
    main()
