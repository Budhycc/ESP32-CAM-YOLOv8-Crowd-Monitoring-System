# Documentation Program Server ESP32-CAM YOLOv8 Crowd Monitoring

Program ini merupakan modul server berbasis Python dalam arsitektur **Client-Server** untuk pemantauan tingkat keramaian ruangan berbasis deteksi manusia (YOLOv8) secara real-time.

---

## Modul dan Komponen Program

1. `config.py`: Pengaturan port WebSocket, kapasitas default ruangan, threshold keramaian, dan nama file database.
2. `database.py`: Pengelolaan database SQLite (`detections.db`) dengan dukungan Multi-Camera. Menyimpan konfigurasi ruangan (tabel `rooms`) dan log deteksi historis (tabel `detection_logs`).
3. `classifier.py`: Klasifikasi tingkat keramaian (`Aman` ≤30%, `Waspada` 30-70%, `Padat` >70%).
4. `detector.py`: Memuat model YOLOv8 secara otomatis dengan optimasi Hardware (OpenVINO CPU/iGPU atau NVIDIA CUDA), decode citra, dan mengekstrak metrik *confidence*.
5. `main.py`: Main entry point. Berfungsi ganda sebagai:
   - Asyncio WebSocket Server penerima aliran video dari berbagai ESP32-CAM.
   - Penyedia stream WebSocket real-time ke Web Dashboard.
   - UDP Auto-Discovery Broadcaster untuk mempermudah koneksi hardware.
   - Local HTTP Server (Port 8000) untuk mengakses halaman Dashboard.
6. `simulator.py`: Skrip pengujian simulasi satu kamera (mengirim frame sintetis atau webcam).
7. `simulator_multi.py`: Skrip pengujian simulasi banyak kamera sekaligus.

---

## Cara Menjalankan

### 1. Install Dependensi
Untuk CPU biasa atau Intel OpenVINO:
```bash
pip install -r requirements.txt
```
*(Untuk pengguna GPU NVIDIA, lihat `requirements-gpu.txt`)*

### 2. Jalankan Server Utama
```bash
python main.py
```
Server akan mulai berjalan dan menyediakan 3 layanan sekaligus:
- **WebSocket Server** (`ws://0.0.0.0:8765`):
  - Endpoint ESP32-CAM: `ws://<IP_SERVER>:8765/ws/esp32/<camera_id>`
  - Endpoint Dashboard: `ws://<IP_SERVER>:8765/ws/dashboard`
- **Dashboard Web Server**: `http://localhost:8000`
- **UDP Auto-Discovery**: Berjalan secara diam-diam di background memancarkan broadcast (Port 9876).

### 3. Simulasi Pengujian (Tanpa Hardware ESP32-CAM)
Jalankan simulator di terminal baru:
```bash
# Simulasi 1 Kamera (Karakter Sintetis)
python simulator.py --mode synthetic --fps 5

# Simulasi 1 Kamera (Menggunakan Webcam Laptop)
python simulator.py --mode webcam --fps 5

# Simulasi 3 Kamera Sekaligus
python simulator_multi.py --count 3 --fps 5
```
