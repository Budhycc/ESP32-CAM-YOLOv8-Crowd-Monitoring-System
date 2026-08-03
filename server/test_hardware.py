import logging
from detector import ObjectDetector

# Matapkan logging dasar agar output terlihat bersih di layar
logging.basicConfig(level=logging.INFO, format="%(message)s")

print("==================================================")
print("     MENGETES DETEKSI HARDWARE UNTUK YOLOv8       ")
print("==================================================\n")

# Menginisialisasi detektor, ini otomatis memicu fungsi auto-deteksi 
# yang ada di dalam server/detector.py (baik CUDA maupun OpenVINO)
try:
    detector = ObjectDetector()
    print("\n==================================================")
    print(f"KESIMPULAN: YOLOv8 berjalan menggunakan {detector.device}")
    print("==================================================")
except Exception as e:
    print(f"\n[ERROR] Terjadi kesalahan saat memuat detektor: {e}")
