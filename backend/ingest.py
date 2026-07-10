import os
import csv
import sqlite3
from pypdf import PdfReader

def ingest_orders(csv_path, db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS orders")
    cursor.execute("""
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            customer TEXT,
            product TEXT,
            amount INTEGER,
            status TEXT,
            order_date TEXT
        )
    """)
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [
            (
                row["order_id"],
                row["customer"],
                row["product"],
                int(row["amount"]),
                row["status"],
                row["order_date"]
            )
            for row in reader
        ]
        
    cursor.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
        rows
    )
    conn.commit()
    conn.close()

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(current_dir, "../data")
    csv_file = os.path.join(data_dir, "orders.csv")
    sqlite_db = os.path.join(current_dir, "orders.db")

    ingest_orders(csv_file, sqlite_db)
