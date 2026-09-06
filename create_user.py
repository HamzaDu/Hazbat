import bcrypt
import psycopg2

username = input("Username: ")
password = input("Password: ")
full_name = input("Full name: ")

password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

conn = psycopg2.connect(dbname="bmac", user="hazma", host="localhost")
cur = conn.cursor()
cur.execute(
    "INSERT INTO tbl_users (username, password_hash, full_name, is_admin) VALUES (%s, %s, %s, %s)",
    (username, password_hash, full_name, True)
)
conn.commit()
cur.close()
conn.close()
print(f"User '{username}' created.")