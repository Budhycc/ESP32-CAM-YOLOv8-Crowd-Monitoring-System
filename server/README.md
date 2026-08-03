# Documentation Program Server ESP32-CAM YOLOv8 Crowd Monitoring

Program ini merupakan modul server berbasis Python dalam arsitektur **Client-Server** untuk pemantauan tingkat keramaian ruangan berbasis deteksi manusia (YOLOv8) secara real-time.

---

## Modul dan Komponen Program

1. `config.py`: Pengaturan port WebSocket, kapasitas ruangan, threshold keramaian, dan model YOLO.
2. `database.py`: Pengelolaan database SQLite (`detections.db`) untuk penyimpanan log deteksi (`detection_logs`).
3. `classifier.py`: Klasifikasi tingkat keramaian (`Sepi` ≤30%, `Sedang` 30-70%, `Ramai` >70%).
4. `detector.py`: Memuat model YOLOv8, decode citra JPEG dari OpenCV, memfilter kelas `person`, dan menggambar bounding box.
5. `main.py`: Main entry point Asyncio WebSocket Server penerima frame dari ESP32-CAM dan penyedia stream real-time ke Dashboard Web.
6. `simulator.py`: Skrip pengujian simulasi ESP32-CAM (mengirim frame sintetis atau webcam).

---

## Cara Menjalankan

### 1. Install Dependensi
```bash
pip install -r requirements.txt
```

### 2. Jalankan Server Utama
```bash
python main.py
```
Server akan berjalan di `ws://0.0.0.0:8765`:
- Endpoint ESP32-CAM: `ws://<IP_SERVER>:8765/ws/esp32`
- Endpoint Dashboard: `ws://<IP_SERVER>:8765/ws/dashboard`

### 3. Simulasi Pengujian (Tanpa Hardware ESP32-CAM)
Jalankan simulator di terminal baru:
```bash
python simulator.py --mode synthetic --fps 5
```
Atau menggunakan webcam:
```bash
python simulator.py --mode webcam --fps 5
```
