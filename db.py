import os
import duckdb
from sqlalchemy import create_engine

DB_PATH = os.getenv("DB_PATH", "data/chinook.duckdb")

def get_engine():
    """Return a SQLAlchemy engine pointed at the local DuckDB file."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    return create_engine(f"duckdb:///{DB_PATH}")

def bootstrap_database():
    """Seeds a local Chinook demo database if not already present."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
        return

    con = duckdb.connect(DB_PATH)
    existing = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
    if existing:
        con.close()
        return

    con.execute("""
        CREATE TABLE artists (artist_id INTEGER PRIMARY KEY, name VARCHAR);
        CREATE TABLE albums (album_id INTEGER PRIMARY KEY, title VARCHAR, artist_id INTEGER REFERENCES artists(artist_id));
        CREATE TABLE tracks (track_id INTEGER PRIMARY KEY, name VARCHAR, album_id INTEGER REFERENCES albums(album_id), genre VARCHAR, unit_price DECIMAL(10,2));
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name VARCHAR, last_name VARCHAR, country VARCHAR);
        CREATE TABLE invoices (invoice_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id), invoice_date DATE, total DECIMAL(10,2));
        CREATE TABLE invoice_items (invoice_item_id INTEGER PRIMARY KEY, invoice_id INTEGER REFERENCES invoices(invoice_id), track_id INTEGER REFERENCES tracks(track_id), unit_price DECIMAL(10,2), quantity INTEGER);
    """)

    con.execute("""
        INSERT INTO artists VALUES (1, 'AC/DC'), (2, 'Aerosmith'), (3, 'Daft Punk'), (4, 'Radiohead');
        INSERT INTO albums VALUES (1, 'Back In Black', 1), (2, 'Toys In The Attic', 2), (3, 'Discovery', 3), (4, 'OK Computer', 4);
        INSERT INTO tracks VALUES (1, 'Back In Black', 1, 'Rock', 0.99), (2, 'Hells Bells', 1, 'Rock', 0.99), (3, 'Walk This Way', 2, 'Rock', 0.99), (4, 'One More Time', 3, 'Dance', 1.29), (5, 'Paranoid Android', 4, 'Alternative', 1.29);
        INSERT INTO customers VALUES (1, 'Maria', 'Silva', 'Brazil'), (2, 'John', 'Smith', 'USA'), (3, 'Emma', 'Clark', 'UK');
        INSERT INTO invoices VALUES (1, 1, '2024-01-05', 2.97), (2, 2, '2024-02-14', 1.98), (3, 3, '2024-03-01', 1.29);
        INSERT INTO invoice_items VALUES (1, 1, 1, 0.99, 1), (2, 1, 2, 0.99, 1), (3, 1, 3, 0.99, 1), (4, 2, 4, 1.29, 1), (5, 2, 3, 0.99, 1), (6, 3, 5, 1.29, 1);
    """)
    con.close()
