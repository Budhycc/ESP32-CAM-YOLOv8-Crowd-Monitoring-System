import os

# Server Network Configuration
HOST = os.getenv("SERVER_HOST", "0.0.0.0")
PORT = int(os.getenv("SERVER_PORT", 8765))

# Camera & Room Configuration (now managed in SQLite DB)
DEFAULT_CAPACITY = 30

# Crowd Density Thresholds (Percentages)
# ≤ 30% -> Sepi
# 30% - 70% -> Sedang
# > 70% -> Ramai
SEPI_MAX_RATIO = 0.30
SEDANG_MAX_RATIO = 0.70

# YOLOv8 Detection Settings
YOLO_MODEL_PATH = os.getenv("YOLO_MODEL_PATH", "yolov8n.pt")
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", 0.45))
TARGET_CLASS_ID = 0  # 0 is 'person' in standard COCO dataset

# Database Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "detections.db"))
