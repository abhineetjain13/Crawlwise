import sqlite3

conn = sqlite3.connect('crawlerai.db')
cur = conn.cursor()
cur.execute("SELECT id, source_url FROM crawl_records WHERE source_url LIKE '%digikey%' ORDER BY id DESC LIMIT 5")
rows = cur.fetchall()

with open('records_out.txt', 'w') as f:
    f.write(str(rows) + "\n")
    for r in rows:
        cur.execute("SELECT data, raw_data, discovered_data FROM crawl_records WHERE id=?", (r[0],))
        record = cur.fetchone()
        f.write(f"\nID: {r[0]}\nURL: {r[1]}\nData: {record[0]}\nRaw Data: {record[1]}\nDiscovered Data: {record[2]}\n")
