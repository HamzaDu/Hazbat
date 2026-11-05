from core.db import get_connection

def test_database_connection():
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    cur.execute("SELECT material_id, chemistry FROM tbl_materials;")
    rows = cur.fetchall()

    print("Connected successfully. Materials in the database:")
    for row in rows:
        print(row)

    cur.close()
    conn.close()