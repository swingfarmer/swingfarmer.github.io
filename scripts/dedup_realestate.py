"""REAL_ESTATE 중복 제거 — low DSN + NO_PARALLEL + 월별"""
import os, oracledb

conn = oracledb.connect(
    user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD',''),
    dsn='db1007_low', config_dir=os.path.expanduser('~/wallet'),
    wallet_location=os.path.expanduser('~/wallet'),
    wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD',''))
cur = conn.cursor()

cur.execute("SELECT prop_type, COUNT(*) FROM real_estate GROUP BY prop_type ORDER BY prop_type")
print("=== 현재 건수 ===")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]:,}건")

total_deleted = 0

for prop in ['OFT','COM']:
    for year in range(2006, 2028):
        for month in range(1, 13):
            cur.execute("""SELECT /*+ NO_PARALLEL */
                ROWID, region, name, dong, area_m2, floor_no, deal_type,
                NVL(price,0), NVL(deposit,0), NVL(monthly_rent,0),
                deal_day, NVL(build_year,0)
                FROM real_estate
                WHERE prop_type=:p AND deal_year=:y AND deal_month=:m
                ORDER BY ROWID
            """, {'p':prop,'y':year,'m':month})

            seen = set()
            to_delete = []
            for row in cur.fetchall():
                rid = row[0]
                key = row[1:]
                if key in seen:
                    to_delete.append(rid)
                else:
                    seen.add(key)

            if not to_delete:
                continue

            for i in range(0, len(to_delete), 200):
                batch = to_delete[i:i+200]
                ph = ','.join([f':r{j}' for j in range(len(batch))])
                params = {f'r{j}': rid for j, rid in enumerate(batch)}
                cur.execute(f"DELETE /*+ NO_PARALLEL */ FROM real_estate WHERE ROWID IN ({ph})", params)
                conn.commit()

            total_deleted += len(to_delete)
            print(f"  {prop} {year}.{month:02d}: {len(to_delete):,}건", flush=True)

print(f"\n✅ 총 {total_deleted:,}건 삭제")

cur.execute("SELECT prop_type, COUNT(*) FROM real_estate GROUP BY prop_type ORDER BY prop_type")
print("\n=== 삭제 후 건수 ===")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]:,}건")
cur.close(); conn.close()
