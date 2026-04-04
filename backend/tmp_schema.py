import sqlite3

conn = sqlite3.connect('crawlerai.db')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cur.fetchall()

with open('schema_out.txt', 'w') as f:
    f.write("Tables: " + str(tables) + "\n")
    for t in tables:
        cur.execute(f"PRAGMA table_info({t[0]});")
        f.write(t[0] + " " + str(cur.fetchall()) + "\n")

# Let's see records
cur.execute("SELECT id, url FROM records WHERE url LIKE '%digikey%' ORDER BY id DESC LIMIT 5")
rows = cur.fetchall()
with open('records_out.txt', 'w') as f:
    f.write(str(rows) + "\n")

    if rows:
        cur.execute("SELECT data_json, llm_enriched_json FROM records WHERE id=?", (rows[0][0],))
        r = cur.fetchone()
        f.write(f"Data: {r[0]}\nLLM Enriched: {r[1]}\n")

