import psycopg2

conn = psycopg2.connect(
    dbname="bmac",
    user="hazma",
    host="localhost"
)

cur = conn.cursor()
cur.execute("SELECT material_id, chemistry FROM tbl_materials;")
rows = cur.fetchall()

print("Connected successfully. Materials in the database:")
for row in rows:
    print(row)

cur.close()
conn.close()