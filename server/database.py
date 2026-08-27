import sqlite3
import datetime
import logging
from config import DB_PATH

logger = logging.getLogger("DatabaseManager")

def get_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # WAL mode: reader tidak blokir writer dan sebaliknya → throughput write 3-5×
    # NORMAL sync: aman untuk monitoring data, jauh lebih cepat dari FULL (default)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
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
            
        columns = [
            ('resolution', 'TEXT DEFAULT "VGA"'),
            ('show_bbox', 'BOOLEAN DEFAULT 1'),
            ('fps', 'INTEGER DEFAULT 0'),
            ('xclk', 'INTEGER DEFAULT 20000000'),
            ('jpeg_quality', 'INTEGER DEFAULT 20'),
            ('fb_count', 'INTEGER DEFAULT 2'),
            ('brightness', 'INTEGER DEFAULT 1'),
            ('contrast', 'INTEGER DEFAULT 1'),
            ('saturation', 'INTEGER DEFAULT -1'),
            ('vflip', 'INTEGER DEFAULT 0'),
            ('use_clahe', 'BOOLEAN DEFAULT 0'),
            ('use_frame_avg', 'BOOLEAN DEFAULT 0'),
            ('use_adaptive_conf', 'BOOLEAN DEFAULT 0'),
            ('use_yolo', 'BOOLEAN DEFAULT 1')
        ]
        for col_name, col_type in columns:
            try:
                cursor.execute(f'ALTER TABLE rooms ADD COLUMN {col_name} {col_type}')
            except sqlite3.OperationalError:
                pass


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
        cursor.execute('SELECT room_id, capacity, esp32_id, resolution, show_bbox, fps, xclk, jpeg_quality, fb_count, brightness, contrast, saturation, vflip, use_clahe, use_frame_avg, use_adaptive_conf, use_yolo FROM rooms ORDER BY room_id')
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
        
        # Ensure 1-to-1 mapping: detach this esp32_id from any other room
        if esp32_id is not None:
            cursor.execute('UPDATE rooms SET esp32_id = NULL WHERE esp32_id = ? AND room_id != ?', (esp32_id, room_id))
            
        cursor.execute('''
            INSERT INTO rooms (room_id, capacity, esp32_id, resolution, show_bbox, fps, xclk, jpeg_quality, fb_count, brightness, contrast, saturation, vflip, use_clahe, use_frame_avg, use_adaptive_conf, use_yolo)
            VALUES (?, ?, ?, "VGA", 1, 0, 20000000, 20, 2, 1, 1, -1, 0, 0, 0, 0, 1)
            ON CONFLICT(room_id) DO UPDATE SET capacity=excluded.capacity, esp32_id=excluded.esp32_id
        ''', (room_id, capacity, esp32_id))
        conn.commit()

def update_room_ui_settings(room_id: str, resolution: str = None, show_bbox: bool = None, fps: int = None,
                            xclk: int = None, jpeg_quality: int = None, fb_count: int = None,
                            brightness: int = None, contrast: int = None, saturation: int = None, vflip: int = None,
                            use_clahe: bool = None, use_frame_avg: bool = None, use_adaptive_conf: bool = None,
                            use_yolo: bool = None):
    """Updates the UI preferences for a room menggunakan satu query UPDATE dinamis (vs N query terpisah)."""
    # Field yang memakai representasi boolean (True/False → 1/0 di SQLite)
    bool_fields = {'show_bbox', 'use_clahe', 'use_frame_avg', 'use_adaptive_conf', 'use_yolo'}
    all_params = {
        'resolution': resolution, 'show_bbox': show_bbox, 'fps': fps,
        'xclk': xclk, 'jpeg_quality': jpeg_quality, 'fb_count': fb_count,
        'brightness': brightness, 'contrast': contrast, 'saturation': saturation,
        'vflip': vflip, 'use_clahe': use_clahe, 'use_frame_avg': use_frame_avg,
        'use_adaptive_conf': use_adaptive_conf, 'use_yolo': use_yolo,
    }
    # Filter None, terapkan konversi bool→int untuk kolom boolean
    updates = {
        k: (1 if v else 0) if k in bool_fields else v
        for k, v in all_params.items() if v is not None
    }
    if not updates:
        return

    fields_sql = ', '.join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [room_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE rooms SET {fields_sql} WHERE room_id = ?", values)

def delete_room(room_id: str):
    """Deletes a room configuration."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM rooms WHERE room_id = ?', (room_id,))
        conn.commit()

def rename_room(old_room_id: str, new_room_id: str):
    """Renames a room and updates all related detection logs."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Update the rooms table
        cursor.execute('UPDATE rooms SET room_id = ? WHERE room_id = ?', (new_room_id, old_room_id))
        # Update detection logs to reflect the new name
        cursor.execute('UPDATE detection_logs SET kamera_id = ? WHERE kamera_id = ?', (new_room_id, old_room_id))
        conn.commit()
