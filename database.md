# Struktur Database ESP32-CAM YOLOv8

Sistem ini menggunakan **SQLite3** sebagai basis data utama. Database disimpan dalam file lokal bernama `detections.db`.

Terdapat dua tabel utama dalam database ini: `rooms` dan `detection_logs`.

---

## 1. Tabel `rooms`
Tabel ini digunakan untuk menyimpan konfigurasi dan daftar ruangan yang terdaftar di sistem, beserta batas kapasitas maksimum ruangan tersebut dan perangkat ESP32 yang terhubung.

| Nama Kolom | Tipe Data | Keterangan |
| :--- | :--- | :--- |
| `room_id` | `TEXT` | **(PRIMARY KEY)** Nama atau ID unik dari ruangan (misalnya: `Ruang_A`). |
| `capacity` | `INTEGER` | Kapasitas maksimum ruangan (digunakan untuk menentukan status keramaian). |
| `esp32_id` | `TEXT` | Hardware ID dari ESP32-CAM yang saat ini ditugaskan ke ruangan ini. Bernilai `NULL` atau kosong jika tidak ada kamera yang di-assign. |
| `resolution` | `TEXT` | Pengaturan resolusi untuk streaming video dari ESP32 (contoh: `"VGA"`, `"HD"`). Default-nya adalah `"VGA"`. |
| `show_bbox` | `BOOLEAN` | Preferensi tampilan *bounding box* deteksi orang di dashboard (1 = Aktif, 0 = Nonaktif). Default-nya adalah `1`. |

**Relasi / Aturan:**
- Satu `esp32_id` hanya boleh terikat pada satu `room_id`. Jika sebuah ESP32 di-assign ke ruangan baru, sistem akan otomatis melepaskannya (menghapus `esp32_id`) dari ruangan yang lama.
- Jika nama `room_id` diubah (rename), sistem juga akan memperbarui secara otomatis semua catatan historis di tabel `detection_logs` agar tetap sinkron.

---

## 2. Tabel `detection_logs`
Tabel ini digunakan untuk menyimpan riwayat historis hasil deteksi manusia (orang) yang dikirim oleh sistem AI (YOLOv8) dari waktu ke waktu.

| Nama Kolom | Tipe Data | Keterangan |
| :--- | :--- | :--- |
| `id` | `INTEGER` | **(PRIMARY KEY, AUTOINCREMENT)** Nomor urut unik untuk setiap entri log. |
| `waktu` | `TIMESTAMP` | Waktu saat deteksi dilakukan. Nilai default-nya adalah `CURRENT_TIMESTAMP`. |
| `kamera_id` | `TEXT` | Merujuk pada ruangan tempat kamera berada (misalnya: `Ruang_A`). Jika kamera belum di-assign, formatnya adalah `Unassigned (ESP_ID)`. |
| `jumlah_orang` | `INTEGER` | Jumlah orang yang berhasil dideteksi oleh YOLOv8 pada *frame* gambar tersebut. |
| `status_keramaian` | `TEXT` | Status keramaian yang dihitung berdasarkan jumlah orang dibagi kapasitas (contoh: `"Sepi"`, `"Sedang"`, `"Ramai"`). |
| `confidence_rata2` | `REAL` | Nilai rata-rata tingkat keyakinan (akurasi) model YOLOv8 untuk seluruh objek manusia yang terdeteksi di *frame* tersebut (contoh: `0.85`). |

**Siklus Data:**
Setiap kali AI selesai memproses satu gambar (frame) dari ESP32, sebuah *record* baru akan dimasukkan ke tabel ini. Data ini kemudian digunakan oleh Dashboard untuk menampilkan grafik riwayat keramaian.
