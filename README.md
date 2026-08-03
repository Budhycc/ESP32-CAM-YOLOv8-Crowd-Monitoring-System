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
2. Edit baris konfigurasi WiFi (`ssid` dan `password`) serta alamat IP Server Python (`websocket_server`).
3. Pastikan menginstal library **WebSockets** by *Markus Sattler* di Library Manager Arduino.
4. Upload kode ke board ESP32-CAM Anda.

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
```bash
cd server
pip install -r requirements.txt
python main.py
```
*(Catatan: Anda juga bisa menggunakan `python simulator.py` jika belum memiliki perangkat keras ESP32-CAM untuk simulasi).*

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
