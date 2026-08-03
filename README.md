# ESP32-CAM YOLOv8 Crowd Monitoring System

Sistem terintegrasi untuk pemantauan tingkat kepadatan keramaian dalam suatu ruangan berbasis **Computer Vision** menggunakan arsitektur **Client-Server-Dashboard**. 

Sistem ini mendeteksi keberadaan orang menggunakan model AI **YOLOv8** dan ESP32-CAM yang di-trigger oleh sensor PIR untuk mengirimkan gambar (frame) ke server Python via **WebSocket**, kemudian menampilkannya secara langsung ke **Web Dashboard** modern.

---

## Struktur Proyek

Proyek ini dibagi menjadi tiga modul utama:

- **`esp32cam/`**: Berisi kode Arduino/C++ untuk perangkat keras ESP32-CAM.
- **`server/`**: Berisi backend Python yang memproses AI Object Detection (YOLOv8) dan WebSocket Server.
- **`dashboard/`**: Berisi frontend (HTML/CSS/JS) untuk antarmuka pemantauan *real-time*.

---

## Modul 1: ESP32-CAM (IoT Client)

Bertugas sebagai pengambil gambar (kamera) yang pintar. Ia hanya akan mengirimkan gambar apabila sensor PIR mendeteksi pergerakan, untuk menghemat daya dan *bandwidth*.

### Cara Penggunaan:
1. Buka file `esp32cam/esp32cam.ino` menggunakan Arduino IDE.
2. Pastikan Anda menginstal library berikut di Library Manager Arduino:
   - **WiFiManager** (oleh tzapu)
   - **WebSockets** (oleh Markus Sattler)
3. Upload kode ke board ESP32-CAM Anda.
4. **Konfigurasi WiFi Pintar (WiFiManager):** Setelah menyala, jika ESP32-CAM belum terhubung ke jaringan, ia akan memancarkan WiFi *Access Point* bernama `ESP32-CAM-SETUP`. Hubungkan HP/Laptop Anda ke WiFi tersebut dan ikuti instruksi di layar (Captive Portal) untuk memasukkan SSID dan Password jaringan rumah Anda.
5. **Auto-Discovery Server:** ESP32-CAM akan secara otomatis mencari alamat IP Server Python di jaringan lokal melalui UDP (Port 9876). Anda tidak perlu lagi men-setting IP server secara manual.
6. **Reset Konfigurasi WiFi:** Jika Anda memindahkan perangkat ke jaringan WiFi baru, buka **Serial Monitor** (baud rate 115200), lalu ketik perintah `RESET_WIFI` dan tekan Enter/Send. Kredensial lama akan terhapus dan ESP32-CAM akan restart ke mode Setup.

---

## Modul 2: Server Python (AI & Backend)

Server ini menggunakan `asyncio` dan `websockets` untuk melayani koneksi ke ESP32-CAM dan Dashboard secara bersamaan. Ia menggunakan YOLOv8 (Ultralytics) untuk menghitung jumlah orang.

### Fitur Utama:
- Mendekode *stream* JPEG dari ESP32-CAM.
- Menjalankan deteksi *object* (Person) secara *real-time*.
- Mengklasifikasikan tingkat kepadatan ruangan.
- Menyimpan histori deteksi ke database SQLite (`detections.db`).
- Menyiarkan (*broadcast*) hasil frame biner (base64) & data analitik ke web dashboard.

### Cara Menjalankan:

1. Masuk ke folder server:
   ```bash
   cd server
   ```
2. **(Opsional)** Buat dan aktifkan *Virtual Environment* (Venv) untuk menghindari bentrok versi library dengan sistem:
   ```bash
   # Membuat environment
   python3 -m venv .venv

   # Mengaktifkan environment (Pilih sesuai OS Anda)
   source .venv/bin/activate      # Untuk Linux/Mac
   .\.venv\Scripts\activate       # Untuk Windows
   ```
3. Install *dependencies* dan jalankan server:
   ```bash
   pip install -r requirements.txt
   python main.py
   ```

### Optimasi Hardware (NVIDIA & INTEL)

Sistem pendeteksi keramaian ini telah dilengkapi dengan fitur "Auto-Detection Hardware". Program akan otomatis memilih hardware tercepat yang Anda miliki dalam urutan prioritas berikut:
1. **NVIDIA GPU (CUDA)** - Sangat Cepat
2. **Intel HD/UHD iGPU (OpenVINO)** - Cepat
3. **Intel CPU (OpenVINO)** - Lumayan Cepat
4. **CPU Standar** - Lambat

#### A. Pengguna GPU NVIDIA (GTX, RTX, MX, dll)
1. Hapus versi PyTorch lama (agar tidak bentrok):
   ```bash
   pip uninstall torch torchvision torchaudio ultralytics -y
   ```
2. Buka terminal di dalam folder `server` dan install PyTorch CUDA 12.1:
   ```bash
   pip install -r requirements-gpu.txt
   ```
*(Khusus Windows: Jika YOLOv8 masih berjalan di CPU, install ulang secara paksa menggunakan Command Prompt/PowerShell:)*
```bash
pip uninstall torch torchvision torchaudio -y
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

#### B. Pengguna Laptop/PC INTEL (Tanpa VGA NVIDIA)
Jika Anda menggunakan laptop/PC bertenaga Intel (Gen 9 ke atas) dan hanya memiliki Intel HD/UHD/Iris Graphics:
1. Install library OpenVINO:
   ```bash
   pip install openvino
   ```
2. Jalankan server seperti biasa (`python main.py`). 
*(Catatan: Saat pertama kali dijalankan, program akan memakan waktu sekitar 1 menit untuk mengkonversi model YOLO menjadi format khusus Intel (OpenVINO). Proses ini normal dan hanya terjadi SATU KALI saja).*

#### C. Mengaktifkan INTEL iGPU di Linux (Opsional)
Jika menggunakan OS Linux (Ubuntu, Fedora, Arch) dan ingin OpenVINO maksimal menggunakan GPU Bawaan Intel (iGPU), lakukan dua langkah berikut:

**Langkah 1: Install Driver Komputasi (OpenCL)**
- Ubuntu/Debian/Mint: `sudo apt-get install intel-opencl-icd`
- Fedora/RHEL: `sudo dnf install intel-compute-runtime`
- Arch/Manjaro: `sudo pacman -S intel-compute-runtime`

**Langkah 2: Memberikan Hak Akses (Group Permission)**
Masukkan user Anda ke grup `video` dan `render`:
```bash
sudo usermod -aG video,render $USER
```
**SANGAT PENTING**: Setelah perintah di atas, Anda **WAJIB me-restart (reboot)** komputer/laptop Anda agar perizinannya aktif!

### Cara Mengetes Hardware
Untuk mengecek hardware apa yang aktif dan dideteksi sistem, jalankan file `test_hardware.py`:
```bash
cd server
python test_hardware.py
```

### Cara Penggunaan Simulator (Jika Tidak Ada ESP32-CAM)

Jika Anda belum memiliki hardware ESP32-CAM, Anda bisa mensimulasikannya. Simulator menggunakan fitur "Auto-Discovery" untuk otomatis mencari alamat IP server.

1. Pastikan server utama (`main.py`) sudah berjalan di satu terminal.
2. Buka terminal/Command Prompt **BARU**.
3. Masuk ke folder server:
   ```bash
   cd server
   ```
4. Jalankan simulator dengan salah satu mode berikut:
   
   **a) Mode Karakter Buatan (Synthetic):**
   *(Menampilkan gambar ilustrasi orang yang otomatis berubah jumlahnya)*
   ```bash
   python simulator.py --mode synthetic
   ```
   
   **b) Mode Webcam (Kamera Laptop):**
   *(Mengambil gambar dari webcam laptop Anda)*
   ```bash
   python simulator.py --mode webcam
   ```

*Opsi Tambahan: Anda bisa mengatur kecepatan frame dengan flag `--fps` (Contoh: `python simulator.py --mode synthetic --fps 2`).*

---

## Modul 3: Web Dashboard (Frontend)

Dashboard berbasis web untuk menampilkan analisis *real-time* yang elegan dengan gaya *glassmorphism* dan dukungan *Dark Mode*.

### Fitur Utama:
- **Live Video Feed**: Menampilkan tangkapan layar ESP32-CAM beserta *bounding-box* hasil deteksi AI.
- **Metrik Responsif**: Menampilkan jumlah orang (vs kapasitas), tingkat persentase kepadatan (Aman/Waspada/Padat).
- **Log Riwayat**: Mencatat riwayat deteksi keramaian terbaru yang terekam.

### Cara Menjalankan:
1. Pastikan modul Server (Backend) sedang berjalan.
2. Buka folder `dashboard/`.
3. Klik ganda pada file `index.html` untuk membukanya di browser (Chrome/Edge/Firefox). Tidak memerlukan server web eksternal. 
*(Pastikan IP pada `app.js` sudah disesuaikan jika server dan dashboard berada di komputer/perangkat yang berbeda).*

---

## Alur Kerja Sistem (Workflow)

1. **Trigger PIR**: Orang masuk ruangan -> Sensor PIR menyala (HIGH).
2. **Kamera Memotret**: ESP32-CAM menjepret frame dan mengirimkannya ke `ws://<IP_SERVER>:8765/ws/esp32` dalam bentuk binary.
3. **Pemrosesan AI**: Server Python menerima gambar, YOLOv8 menghitung jumlah orang & menggambar kotak hijau (bounding box).
4. **Distribusi Data**: Server mengirim balik status keramaian dan gambar base64 ke `ws://<IP_SERVER>:8765/ws/dashboard`.
5. **Tampilan Dashboard**: Dashboard web secara *real-time* mengubah UI (Indikator warna, Jumlah Orang, Frame Video).

---
*Dibuat untuk keperluan otomatisasi AI berbasis Edge-Cloud.*
