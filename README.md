# ESP32-CAM YOLOv8 Crowd Monitoring System

Sistem terintegrasi untuk pemantauan tingkat kepadatan keramaian dalam suatu ruangan berbasis **Computer Vision** menggunakan arsitektur **Client-Server-Dashboard**.

Sistem ini mendeteksi keberadaan orang menggunakan model AI **YOLOv8** dan perangkat **ESP32-CAM AI Thinker** yang di-trigger oleh sensor PIR untuk mengirimkan frame ke server Python via **WebSocket**, kemudian menampilkannya secara langsung ke **Web Dashboard** modern.

---

## Struktur Proyek

```
esp32cam-yolov8/
├── esp32cam/
│   └── esp32cam.ino          # Firmware Arduino untuk ESP32-CAM AI Thinker
├── server/
│   ├── main.py               # WebSocket server utama (asyncio)
│   ├── detector.py           # YOLOv8 inference engine (OpenVINO / CUDA)
│   ├── config.py             # Konfigurasi sistem (path model, threshold, dll)
│   ├── simulator.py          # Simulator satu kamera (untuk testing tanpa hardware)
│   ├── simulator_multi.py    # Simulator banyak kamera sekaligus
│   ├── requirements.txt      # Dependencies untuk CPU / Intel
│   └── requirements-gpu.txt  # Dependencies tambahan untuk GPU NVIDIA
├── dashboard/
│   └── index.html            # Web Dashboard real-time (glassmorphism UI)
└── README.md
```

---

## Modul 1: ESP32-CAM (IoT Client)

Bertugas sebagai pengambil gambar (kamera) yang pintar. Hanya mengirim frame saat sensor PIR mendeteksi pergerakan untuk menghemat daya dan bandwidth.

### Spesifikasi Hardware yang Didukung

- **ESP32-CAM AI Thinker** (direkomendasikan & telah diuji)

### Konfigurasi Kamera (sudah dioptimasi)

| Parameter | Nilai | Keterangan |
|---|---|---|
| XCLK | 20 MHz | Stabil di semua board AI Thinker |
| Resolusi default | VGA (640×480) | Seimbang antara detail & kecepatan |
| JPEG Quality | 20 | Skala ESP32 terbalik: 20 = ~12KB/frame, cepat di WiFi |
| DMA Buffer | 2 | Aman & stabil untuk semua board AI Thinker |
| Sensor OV2640 | Tuning aktif | Brightness, contrast, AWB, lens correction |

> **Catatan JPEG Quality ESP32-CAM**: Skala di ESP32 **terbalik** dari intuisi — angka **lebih kecil = kualitas LEBIH TINGGI = file LEBIH BESAR**. Nilai 20 dipilih untuk menghasilkan file kecil (~12KB) yang cukup tajam untuk deteksi YOLOv8.

### Cara Upload Firmware:
1. Buka `esp32cam/esp32cam.ino` di **Arduino IDE**.
2. Pastikan library berikut sudah terinstall (Library Manager):
   - **WiFiManager** (oleh tzapu)
   - **WebSockets** (oleh Markus Sattler)
3. Pilih board: **AI Thinker ESP32-CAM**, port COM yang sesuai.
4. Upload ke board ESP32-CAM.

### Konfigurasi WiFi (Otomatis via WiFiManager):
- Setelah menyala, jika belum tersambung WiFi, ESP32-CAM memancarkan AP bernama `ESP32-CAM-SETUP`.
- Hubungkan HP/Laptop ke AP tersebut → isi SSID & password WiFi rumah di Captive Portal.

### Auto-Discovery Server:
- ESP32-CAM **otomatis mencari IP server** Python di jaringan lokal via UDP (port 9876).
- Tidak perlu setting IP server secara manual.

### Reset Konfigurasi WiFi (Jika Pindah Jaringan):
- **Tombol BOOT**: Tekan tahan GPIO 0 selama **5 detik** → WiFi reset & restart.
- **Serial Command**: Kirim `RESET_WIFI` via Serial Monitor (baud 115200).

---

## Modul 2: Server Python (AI & Backend)

Server berbasis `asyncio` + `websockets` untuk melayani koneksi ESP32-CAM dan Dashboard secara bersamaan.

### Fitur Utama:
- Mendekode stream JPEG dari ESP32-CAM secara real-time.
- Inference **YOLOv8** untuk mendeteksi dan menghitung orang (`imgsz=416` dioptimasi untuk kecepatan).
- Klasifikasi tingkat kepadatan ruangan (Sepi / Sedang / Padat / Sangat Padat).
- Penyimpanan histori ke database **SQLite** (`detections.db`), throttled 1x/detik per kamera.
- Broadcast frame + analitik ke dashboard, throttled 5 FPS per kamera untuk hemat bandwidth.
- **Room lookup cache** berbasis `dict` untuk O(1) lookup per frame.
- **ThreadPoolExecutor** dedikasi untuk inference agar tidak memblok event loop asyncio.

### Cara Menjalankan:

```bash
# 1. Masuk ke folder proyek
cd esp32cam-yolov8

# 2. Buat dan aktifkan Virtual Environment (direkomendasikan)
python3 -m venv .venv
source .venv/bin/activate      # Linux/Mac
# .venv\Scripts\activate       # Windows

# 3. Install dependencies
pip install -r server/requirements.txt

# 4. Jalankan server
cd server
python3 main.py
```

Server akan otomatis:
- Memuat model YOLOv8 (`yolov8n.pt`)
- Mengekspor ke format **OpenVINO** dengan `imgsz=416` (hanya sekali, ~1–2 menit)
- Menyalakan WebSocket server di port **8765**
- Menyalakan HTTP dashboard server di port **8000**
- Menyalakan UDP Auto-Discovery broadcaster di port **9876**

### Mengganti Model YOLO

1. Letakkan file `.pt` baru di folder `server/`
2. Update `config.py`:
   ```python
   YOLO_MODEL_PATH = os.getenv("YOLO_MODEL_PATH", "yolov8s.pt")
   ```
3. **Hapus folder OpenVINO lama** agar model baru di-export ulang:
   ```bash
   rm -rf server/yolov8n_openvino_model/
   ```
4. Restart server — export otomatis terjadi saat startup.

> **Penting**: Folder export OpenVINO (`*_openvino_model/`) dikompilasi dengan `imgsz=416`. Jika ganti model, folder lama HARUS dihapus dahulu agar tidak terjadi shape mismatch error.

| Model | Ukuran | Kecepatan (Intel CPU) | Akurasi |
|---|---|---|---|
| `yolov8n.pt` ← default | 6 MB | ⚡ Paling cepat | Dasar |
| `yolov8s.pt` | 22 MB | Cepat | Sedang |
| `yolov8m.pt` | 52 MB | Sedang | Baik |
| Custom `.pt` | varies | varies | Tergantung training |

### Optimasi Hardware (Auto-Detection)

Server otomatis memilih hardware terbaik yang tersedia:

| Prioritas | Hardware | Kecepatan |
|---|---|---|
| 1 | NVIDIA GPU (CUDA) | Sangat Cepat |
| 2 | Intel iGPU (OpenVINO GPU) | Cepat |
| 3 | Intel CPU (OpenVINO CPU) | Lumayan Cepat |
| 4 | CPU Standar (PyTorch) | Lambat |

#### A. GPU NVIDIA (GTX, RTX, MX, dll.)
```bash
pip uninstall torch torchvision torchaudio ultralytics -y
pip install -r server/requirements-gpu.txt
```

#### B. Intel CPU / iGPU (tanpa NVIDIA)
```bash
pip install openvino
```
Jalankan server seperti biasa — model akan otomatis dikonversi ke OpenVINO (sekali saja).

#### C. Aktifkan Intel iGPU di Linux (Opsional)
```bash
# Install driver OpenCL (pilih sesuai distro)
sudo apt-get install intel-opencl-icd        # Ubuntu/Debian
sudo dnf install intel-compute-runtime       # Fedora/RHEL
sudo pacman -S intel-compute-runtime         # Arch

# Tambahkan user ke grup video & render
sudo usermod -aG video,render $USER

# WAJIB reboot setelahnya
sudo reboot
```

#### D. Cek Hardware yang Aktif
```bash
cd server && python3 test_hardware.py
```

---

## Modul 2b: Simulator (Testing Tanpa Hardware ESP32-CAM)

Dua simulator tersedia untuk testing saat hardware tidak ada. Keduanya menggunakan **UDP Auto-Discovery** dan **JPEG quality 20** yang identik dengan hardware asli.

### simulator.py — Satu Kamera

```bash
cd server

# Mode synthetic (frame gambar buatan, tidak butuh webcam)
python3 simulator.py --mode synthetic --fps 10

# Mode webcam (pakai kamera laptop)
python3 simulator.py --mode webcam --fps 10

# Ke server tertentu dengan ID custom
python3 simulator.py --url ws://192.168.1.10:8765/ws/esp32/Sim_1 --fps 10
```

### simulator_multi.py — Banyak Kamera Sekaligus

```bash
cd server

# 3 kamera synthetic (default)
python3 simulator_multi.py --mode synthetic --count 3 --fps 10

# 5 kamera webcam
python3 simulator_multi.py --mode webcam --count 5 --fps 10

# Ke server spesifik
python3 simulator_multi.py --url ws://192.168.1.10:8765 --count 3
```

---

## Modul 3: Web Dashboard (Frontend)

Dashboard berbasis web dengan tampilan *glassmorphism* dan dukungan *Dark Mode*. Seluruh aset (font, ikon) disimpan lokal — dashboard berjalan **100% offline**.

### Fitur Utama:
- **Multi-Camera Support**: Pantau banyak ruangan dalam satu layar.
- **Live Video Feed**: Streaming video real-time dengan info resolusi, FPS, dan latensi.
- **Bounding Box Toggle**: Tampilkan/sembunyikan kotak deteksi AI per kamera.
- **Full-Screen Mode**: Perbesar tampilan satu kamera.
- **Metrik Kepadatan**: Jumlah orang vs kapasitas, persentase, status Aman/Waspada/Padat.
- **Riwayat & Laporan**: Histori deteksi + Export ke CSV (Excel).

### Cara Akses:
```
# Dari komputer yang sama dengan server:
http://localhost:8000

# Dari HP/perangkat lain di jaringan WiFi yang sama:
http://<IP_KOMPUTER_SERVER>:8000
```

---

## Alur Kerja Sistem

```
[PIR Sensor] ──trigger──▶ [ESP32-CAM AI Thinker]
                                    │
                        JPEG binary via WebSocket
                                    │
                                    ▼
                         [Python Server :8765]
                         ┌─────────────────┐
                         │  YOLOv8 + OpenVINO │ ←── imgsz=416 (dioptimasi)
                         │  Hitung Orang    │
                         │  Simpan ke DB    │ ←── throttle 1x/detik
                         └─────────────────┘
                                    │
                      base64 frame + analitik (5 FPS)
                                    │
                                    ▼
                        [Web Dashboard :8000]
                     (Real-time UI, Multi-Camera)
```

---

## Troubleshooting

| Masalah | Penyebab | Solusi |
|---|---|---|
| ESP32-CAM disconnect setelah ~1 detik | XCLK terlalu tinggi atau `set_denoise` tidak didukung | Pastikan firmware terbaru sudah di-upload |
| `Corrupt JPEG data` di log server | Frame terpotong saat transfer WiFi | Normal — server sudah handle dengan skip frame |
| `shape=[1,3,640,640] incompatible` | Folder OpenVINO lama tidak sesuai `imgsz` baru | Hapus `server/yolov8n_openvino_model/` lalu restart |
| `Address already in use` port 8765 | Instance server lain masih berjalan | `fuser -k 8765/tcp && fuser -k 8000/tcp` |

---

*Dikembangkan untuk keperluan otomatisasi AI berbasis Edge-Cloud.*
