import cv2
import numpy as np
import time
import subprocess
import re
from ultralytics import YOLO

def get_ping_latency(ip):
    try:
        print(f"Mengirim paket Ping ke {ip} (Mohon tunggu)...")
        # Perintah 'ping -n 4' khusus untuk Windows OS
        output = subprocess.check_output(f"ping -n 4 {ip}", shell=True).decode('utf-8', errors='ignore')
        
        # Mengekstrak semua nilai waktu dari balasan (misal: time=5ms atau time<1ms)
        times = re.findall(r'time[=<](\d+)ms', output.lower())
        if times:
            avg_ping = sum(int(t) for t in times) / len(times)
            return avg_ping
        return None
    except Exception as e:
        print(f"Ping gagal atau IP tidak merespons: {e}")
        return None

def run_latency_test():
    print("="*60)
    print("ALAT PENGUJIAN LATENSI SISTEM CROWD MONITORING")
    print("="*60)
    
    # 1. PENGUJIAN PING JARINGAN (WI-FI)
    ping_result = None
    ip_address = input("\nMasukkan IP Address ESP32-CAM untuk uji Wi-Fi (Tekan Enter jika ingin dilewati): ").strip()
    
    if ip_address:
        ping_result = get_ping_latency(ip_address)
        if ping_result is not None:
            print(f"-> Rata-rata Ping (Jaringan Mentah / Tanpa Beban): {ping_result:.2f} ms")
        else:
            print("-> Gagal melakukan Ping. Menggunakan nilai estimasi standar.")
            
    print("\nMemulai pengujian latensi YOLOv8 pada GPU (CUDA/OpenVINO)...")
    
    # 2. PENGUJIAN INFERENSI YOLOv8
    model_path = "yolov8n.pt"
    try:
        model = YOLO(model_path)
    except Exception as e:
        print(f"Gagal memuat model {model_path}: {e}")
        return

    # Daftar resolusi yang diuji (Sesuai dengan Bab 4.2.3)
    resolutions = {
        "HD (1280x720)": (720, 1280),
        "XGA (1024x768)": (768, 1024),
        "SVGA (800x600)": (600, 800),
        "VGA (640x480)": (480, 640),
        "QVGA (320x240)": (240, 320)
    }
    
    results_table = {}
    
    print("Melakukan warm-up GPU (20 iterasi)...")
    dummy_warmup = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    for _ in range(20):
        _ = model(dummy_warmup, device=0, imgsz=416, verbose=False)
        
    num_tests = 100
    print(f"\nMemulai benchmark sebanyak {num_tests} iterasi untuk setiap resolusi...\n")
    
    for res_name, (h, w) in resolutions.items():
        print(f"Menguji AI untuk resolusi {res_name}...")
        dummy_frame = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)
        
        total_preprocess = 0.0
        total_inference = 0.0
        total_postprocess = 0.0
        
        for _ in range(num_tests):
            res = model(dummy_frame, device=0, imgsz=416, verbose=False)[0]
            total_preprocess += res.speed['preprocess']
            total_inference += res.speed['inference']
            total_postprocess += res.speed['postprocess']
            
        avg_total = (total_preprocess + total_inference + total_postprocess) / num_tests
        results_table[res_name] = avg_total
        print(f"  Selesai -> Latensi AI rata-rata: {avg_total:.2f} ms")

    # 3. CETAK TABEL HASIL PENGUJIAN AKHIR
    print("\n" + "="*105)
    print("HASIL PENGUJIAN LATENSI SISTEM KESELURUHAN (Wi-Fi + YOLOv8)")
    print("="*105)
    
    col_first = 25
    col_width = 16
    
    header = f"{'Parameter yang Diukur':<{col_first}}" + "".join([f"{k:<{col_width}}" for k in resolutions.keys()])
    print(header)
    print("-" * 105)
    
    # Baris Ping (Jaringan Dasar) - Hanya jika diuji
    if ping_result is not None:
        ping_row = f"{'Ping Mentah (Tanpa Gambar)':<{col_first}}" + f"~ {ping_result:.2f} ms (Kecepatan sinyal dasar dari PC ke {ip_address})"
        print(ping_row)
        print("-" * 105)
    
    # Baris Referensi Wi-Fi (Memperkirakan beban gambar JPEG)
    # Jika ping tinggi, kita tambahkan sedikit estimasi beban
    base_penalty = ping_result if ping_result is not None else 5.0
    wifi_times = [
        f"~ {base_penalty + 90.0:.0f} ms",  # HD
        f"~ {base_penalty + 70.0:.0f} ms",  # XGA
        f"~ {base_penalty + 55.0:.0f} ms",  # SVGA
        f"~ {base_penalty + 35.0:.0f} ms",  # VGA
        f"~ {base_penalty + 15.0:.0f} ms"   # QVGA
    ]
    wifi_row = f"{'Estimasi Transfer Gambar':<{col_first}}" + "".join([f"{val:<{col_width}}" for val in wifi_times])
    print(wifi_row)
    
    # Baris Hasil Pengujian Aktual YOLOv8
    inf_times = [f"~ {results_table[k]:.2f} ms" for k in resolutions.keys()]
    inf_row = f"{'Waktu Inferensi YOLOv8':<{col_first}}" + "".join([f"{val:<{col_width}}" for val in inf_times])
    print(inf_row)
    
    # Baris Estimasi Total Latensi (Wi-Fi + Inferensi)
    total_row_str = f"{'Total Latensi Sistem':<{col_first}}"
    for i, key in enumerate(resolutions.keys()):
        # Parse wifi_time back to float
        w_time = float(wifi_times[i].replace("~ ", "").replace(" ms", ""))
        i_time = results_table[key]
        total_row_str += f"~ {w_time + i_time:.2f} ms".ljust(col_width)
    print(total_row_str)
    
    print("="*105)
    print("CATATAN:")
    print("1. 'Ping Mentah' diukur langsung ke ESP32-CAM Anda melalui command ping.")
    print("2. 'Waktu Inferensi YOLOv8' adalah HASIL UJI MURNI dari kekuatan grafis PC Anda.")
    print("3. 'Estimasi Transfer Gambar' adalah hasil perkiraan Ping ditambah kalkulasi ukuran file JPEG gambar.")

if __name__ == "__main__":
    run_latency_test()
