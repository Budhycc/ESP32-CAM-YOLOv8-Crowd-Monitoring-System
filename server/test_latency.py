import cv2
import numpy as np
import time
from ultralytics import YOLO

def run_latency_test():
    print("Memulai pengujian latensi YOLOv8 pada NVIDIA GPU (CUDA)...")
    
    # Memuat model YOLO
    model_path = "yolov8n.pt"
    try:
        model = YOLO(model_path)
    except Exception as e:
        print(f"Gagal memuat model {model_path}: {e}")
        return

    # Membuat gambar dummy beresolusi VGA (640x480) seperti hasil jepretan ESP32-CAM
    print("Membuat frame uji (640x480)...")
    dummy_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    
    # Warm-up phase (agar GPU inisialisasi selesai dan tidak mempengaruhi waktu test)
    print("Melakukan warm-up GPU (20 iterasi)...")
    for _ in range(20):
        _ = model(dummy_frame, device=0, imgsz=416, verbose=False)
        
    # Benchmark phase
    num_tests = 100
    print(f"Memulai benchmark sebanyak {num_tests} iterasi...")
    
    total_preprocess = 0.0
    total_inference = 0.0
    total_postprocess = 0.0
    
    for i in range(num_tests):
        results = model(dummy_frame, device=0, imgsz=416, verbose=False)[0]
        total_preprocess += results.speed['preprocess']
        total_inference += results.speed['inference']
        total_postprocess += results.speed['postprocess']
        
        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{num_tests}] iterasi selesai...")

    # Menghitung rata-rata
    avg_preprocess = total_preprocess / num_tests
    avg_inference = total_inference / num_tests
    avg_postprocess = total_postprocess / num_tests
    avg_total = avg_preprocess + avg_inference + avg_postprocess
    
    print("\n" + "="*45)
    print("HASIL PENGUJIAN LATENSI (Rata-rata per frame)")
    print("="*45)
    print(f"1. Waktu pre-processing per frame  : {avg_preprocess:.2f} ms")
    print(f"2. Waktu inferensi YOLOv8 per frame: {avg_inference:.2f} ms")
    print(f"3. Waktu post-processing per frame : {avg_postprocess:.2f} ms")
    print("-" * 45)
    print(f"4. Total latensi deteksi per frame : {avg_total:.2f} ms")
    print("="*45)
    print("Silakan masukkan nilai-nilai di atas ke dalam tabel bab 4.md!")

if __name__ == "__main__":
    run_latency_test()
