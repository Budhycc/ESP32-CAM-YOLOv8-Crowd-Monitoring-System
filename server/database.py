import sqlite3
import datetime
import logging
from config import DB_PATH

logger = logging.getLogger("DatabaseManager")

def get_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema if table does not exist."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS detection_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                waktu TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                kamera_id TEXT NOT NULL,
                jumlah_orang INTEGER NOT NULL,
                status_keramaian TEXT NOT NULL,
                confidence_rata2 REAL DEFAULT 0.0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY,
                capacity INTEGER NOT NULL
            )
        ''')
        
        # Add esp32_id column if it doesn't exist
        try:
            cursor.execute('ALTER TABLE rooms ADD COLUMN esp32_id TEXT')
        except sqlite3.OperationalError:
            pass # Column already exists

        # Seed defaults if empty
        cursor.execute('SELECT COUNT(*) FROM rooms')
        if cursor.fetchone()[0] == 0:
            cursor.executemany('''
                INSERT INTO rooms (room_id, capacity, esp32_id) VALUES (?, ?, ?)
            ''', [("Ruang_A", 30, "ESP-001"), ("Ruang_B", 20, "ESP-002")])
        conn.commit()
    logger.info(f"Database initialized at: {DB_PATH}")

def save_detection(kamera_id: str, jumlah_orang: int, status_keramaian: str, confidence_rata2: float = 0.0):
    """
    Saves a single detection record into database.
    
    Data fields:
    - waktu: Current datetime ISO format
    - kamera_id: Identifier of the camera node (e.g. 'Ruang_A')
    - jumlah_orang: Total count of detected persons
    - status_keramaian: 'Sepi', 'Sedang', or 'Ramai'
    - confidence_rata2: Average YOLOv8 confidence score for detected persons
    """
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO detection_logs (waktu, kamera_id, jumlah_orang, status_keramaian, confidence_rata2)
            VALUES (?, ?, ?, ?, ?)
        ''', (now_str, kamera_id, jumlah_orang, status_keramaian, round(confidence_rata2, 2)))
        conn.commit()
        log_id = cursor.lastrowid
    logger.debug(f"Saved log ID {log_id}: {jumlah_orang} orang -> {status_keramaian}")
    return log_id

def get_recent_logs(limit: int = 50):
    """Retrieves recent detection logs sorted descending by timestamp."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, waktu, kamera_id, jumlah_orang, status_keramaian, confidence_rata2
            FROM detection_logs
            ORDER BY id DESC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def get_latest_log():
    """Retrieves the single most recent detection log."""
    logs = get_recent_logs(limit=1)
    return logs[0] if logs else None

def get_all_rooms():
    """Retrieves all room configurations."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT room_id, capacity, esp32_id FROM rooms ORDER BY room_id')
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def get_room_capacity(room_id: str, default: int = 30):
    """Gets capacity for a specific room, or default if not found."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT capacity FROM rooms WHERE room_id = ?', (room_id,))
        row = cursor.fetchone()
        return row['capacity'] if row else default

def get_room_by_esp32(esp32_id: str):
    """Gets room config by ESP32 ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT room_id, capacity FROM rooms WHERE esp32_id = ?', (esp32_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def upsert_room(room_id: str, capacity: int, esp32_id: str = None):
    """Adds or updates a room configuration."""
    if esp32_id == "": esp32_id = None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO rooms (room_id, capacity, esp32_id)
            VALUES (?, ?, ?)
            ON CONFLICT(room_id) DO UPDATE SET capacity=excluded.capacity, esp32_id=excluded.esp32_id
        ''', (room_id, capacity, esp32_id))
        conn.commit()

def delete_room(room_id: str):
    """Deletes a room configuration."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM rooms WHERE room_id = ?', (room_id,))
        conn.commit()
