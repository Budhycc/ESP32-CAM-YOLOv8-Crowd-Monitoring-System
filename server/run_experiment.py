import os
import sys
import time
import cv2
import argparse
import numpy as np
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ExperimentRunner")

# Import modul internal
from simulator_video import VideoReader, JPEG_QUALITY
from detector import ObjectDetector
from classifier import classify_crowd
from config import SEPI_MAX_RATIO, SEDANG_MAX_RATIO

SCENARIOS = {
    # Skenario 1-4 (Baseline)
    "S1": {"resolution": (1280, 720), "name": "HD", "clahe": False, "frame_avg": False, "adaptive_conf": False, "fps": 2},
    "S2": {"resolution": (1024, 768), "name": "XGA", "clahe": False, "frame_avg": False, "adaptive_conf": False, "fps": 4},
    "S3": {"resolution": (800, 600), "name": "SVGA", "clahe": False, "frame_avg": False, "adaptive_conf": False, "fps": 6},
    "S4": {"resolution": (640, 480), "name": "VGA", "clahe": False, "frame_avg": False, "adaptive_conf": False, "fps": 8},
    
    # Skenario 5 (Kondisi S5: Tanpa Mitigasi di Semua Resolusi)
    "S5_HD":   {"resolution": (1280, 720), "name": "HD", "clahe": False, "frame_avg": False, "adaptive_conf": False, "fps": 2},
    "S5_XGA":  {"resolution": (1024, 768), "name": "XGA", "clahe": False, "frame_avg": False, "adaptive_conf": False, "fps": 4},
    "S5_SVGA": {"resolution": (800, 600), "name": "SVGA", "clahe": False, "frame_avg": False, "adaptive_conf": False, "fps": 6},
    "S5_VGA":  {"resolution": (640, 480), "name": "VGA", "clahe": False, "frame_avg": False, "adaptive_conf": False, "fps": 8},
    "S5_QVGA": {"resolution": (320, 240), "name": "QVGA", "clahe": False, "frame_avg": False, "adaptive_conf": False, "fps": 10},
    
    # Skenario 6 (Kondisi S6: Dengan Mitigasi di Semua Resolusi)
    "S6_HD":   {"resolution": (1280, 720), "name": "HD + Mitigasi", "clahe": True, "frame_avg": True, "adaptive_conf": True, "fps": 2},
    "S6_XGA":  {"resolution": (1024, 768), "name": "XGA + Mitigasi", "clahe": True, "frame_avg": True, "adaptive_conf": True, "fps": 4},
    "S6_SVGA": {"resolution": (800, 600), "name": "SVGA + Mitigasi", "clahe": True, "frame_avg": True, "adaptive_conf": True, "fps": 6},
    "S6_VGA":  {"resolution": (640, 480), "name": "VGA + Mitigasi", "clahe": True, "frame_avg": True, "adaptive_conf": True, "fps": 8},
    "S6_QVGA": {"resolution": (320, 240), "name": "QVGA + Mitigasi", "clahe": True, "frame_avg": True, "adaptive_conf": True, "fps": 10},
}

def calculate_metrics(detected, ground_truth):
    """
    Menghitung aproksimasi Precision dan Recall berdasarkan *count*.
    TP = jumlah deteksi yang benar (dibatasi maksimal sesuai ground truth).
    FP = kelebihan deteksi dari ground truth (False Positive).
    FN = orang yang gagal terdeteksi (False Negative).
    """
    tp = min(detected, ground_truth)
    fp = max(0, detected - ground_truth)
    fn = max(0, ground_truth - detected)
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    
    return precision, recall

def run_scenario(scenario_id, config, video_path, detector, args):
    logger.info(f"--- Memulai {scenario_id}: Resolusi {config['name']} {config['resolution']} ---")
    
    # Init VideoReader
    reader = VideoReader(video_path, f"Cam_{scenario_id}")
    reader.start(resolution=config['resolution'])
    
    # Beri waktu VideoReader untuk mendapatkan frame pertama
    time.sleep(1.0)
    
    expected_status = classify_crowd(args.gt_person, args.capacity)["status"]
    
    precisions = []
    recalls = []
    latencies = []
    counts = []
    correct_classifications = 0
    
    frames_processed = 0
    
    while frames_processed < args.frames:
        raw_frame = reader.get_frame()
        if raw_frame is None:
            time.sleep(0.05)
            continue
            
        # Simulasikan kompresi dan transmisi JPEG seperti ESP32-CAM
        ok, encoded = cv2.imencode(".jpg", raw_frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            continue
            
        image_bytes = encoded.tobytes()
        
        # Mulai hitung latensi End-to-End
        start_time = time.time()
        
        # Proses di YOLOv8
        person_count, avg_conf, persons, annotated_bytes, yolo_latency = detector.process_frame(
            image_bytes=image_bytes,
            draw_overlay=True, 
            use_clahe=config["clahe"],
            camera_id=f"Exp_{scenario_id}",
            use_frame_averaging=config["frame_avg"],
            use_adaptive_confidence=config["adaptive_conf"]
        )
        
        # Klasifikasi Kepadatan
        classification = classify_crowd(person_count, args.capacity)
        
        end_time = time.time()
        end_to_end_latency_ms = (end_time - start_time) * 1000
        
        prec, rec = calculate_metrics(person_count, args.gt_person)
        precisions.append(prec)
        recalls.append(rec)
        latencies.append(end_to_end_latency_ms)
        counts.append(person_count)
        
        # Tampilkan Window Bounding Box beserta OSD Metrik Real-Time
        if annotated_bytes:
            nparr = np.frombuffer(annotated_bytes, np.uint8)
            annotated_frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if annotated_frame is not None:
                # Gambar Bounding Box dari data persons
                for p in persons:
                    x1, y1, x2, y2 = p["bbox"]
                    conf = p["confidence"]
                    # Gambar kotak hijau
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    # Label confidence
                    label = f"Person {conf:.2f}"
                    cv2.putText(annotated_frame, label, (x1, max(y1 - 5, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

                # Teks OSD (On-Screen Display)
                cv2.putText(annotated_frame, f"Skenario: {scenario_id} | Res: {config['name']} | Sim FPS: {config.get('fps', 10)}", 
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(annotated_frame, f"Count: {person_count} / GT: {args.gt_person} | Prec: {prec * 100:.1f}% | Rec: {rec * 100:.1f}%", 
                            (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.putText(annotated_frame, f"Latency E2E: {end_to_end_latency_ms:.1f} ms", 
                            (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                cv2.putText(annotated_frame, f"Status: {classification['status']} (Target: {expected_status})", 
                            (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                
                cv2.imshow("Experiment Bounding Box", annotated_frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    logger.info("Pengujian dihentikan secara manual (tombol Q ditekan).")
                    reader.stop()
                    cv2.destroyAllWindows()
                    sys.exit(0)
                    
        if classification["status"] == expected_status:
            correct_classifications += 1
            
        frames_processed += 1
        
        # Simulasi FPS realistis ESP32-CAM dengan Jitter (kadang drop)
        target_fps = config.get("fps", 10)
        base_delay = 1.0 / target_fps
        
        # 15% kemungkinan frame drop (delay bertambah 50-100% lebih lama)
        if np.random.rand() < 0.15:
            base_delay += base_delay * np.random.uniform(0.5, 1.0)
            
        # Potong delay dengan waktu processing agar interval total sama dengan FPS
        processing_time = end_time - start_time
        sleep_time = max(0.01, base_delay - processing_time)
        time.sleep(sleep_time)

    reader.stop()
    cv2.destroyAllWindows()
    
    avg_precision = np.mean(precisions) * 100 if precisions else 0.0
    avg_recall = np.mean(recalls) * 100 if recalls else 0.0
    avg_latency = np.mean(latencies) if latencies else 0.0
    avg_count = np.mean(counts) if counts else 0.0
    accuracy_rate = (correct_classifications / args.frames) * 100
    
    logger.info(f"Hasil {scenario_id}: Count={avg_count:.1f}, Prec={avg_precision:.1f}%, Rec={avg_recall:.1f}%, Acc={accuracy_rate:.1f}%")
    
    return {
        "Scenario": scenario_id,
        "Description": f"{config['name']} ({'Mitigasi' if config['clahe'] else 'Tanpa Mitigasi'})",
        "Avg Count": avg_count,
        "Expected Status": expected_status,
        "Precision (%)": avg_precision,
        "Recall (%)": avg_recall,
        "Latency (ms)": avg_latency,
        "Accuracy (%)": accuracy_rate
    }

def main():
    parser = argparse.ArgumentParser(description="Script Evaluasi Eksperimen S1-S6")
    parser.add_argument("--video", type=str, default="sample/", help="Path ke file video footage atau direktori yang berisi video (default: folder sample/)")
    parser.add_argument("--gt-person", type=int, default=14, help="Ground Truth jumlah orang di dalam video (default: 14)")
    parser.add_argument("--capacity", type=int, default=15, help="Kapasitas ruangan untuk klasifikasi status (default: 15)")
    parser.add_argument("--frames", type=int, default=50, help="Jumlah frame yang diuji per skenario (default: 50)")
    
    args = parser.parse_args()
    
    video_path = args.video
    if os.path.isdir(video_path):
        import glob
        video_files = []
        for ext in ["*.mp4"]:
            video_files.extend(glob.glob(os.path.join(video_path, ext)))
        if not video_files:
            logger.error(f"Tidak ada file video (.mp4) ditemukan di folder {video_path}!")
            sys.exit(1)
        video_path = video_files[0]
        logger.info(f"Menggunakan video footage otomatis: {video_path}")
        
    if not os.path.exists(video_path):
        logger.error(f"Video {video_path} tidak ditemukan!")
        sys.exit(1)
        
    logger.info("Inisialisasi Model YOLOv8 (tunggu sebentar)...")
    detector = ObjectDetector()
    
    results = []
    
    # Jalankan Skenario S1 s/d S6 secara berurutan
    scenario_keys = [
        "S1", "S2", "S3", "S4", 
        "S5_HD", "S5_XGA", "S5_SVGA", "S5_VGA", "S5_QVGA",
        "S6_HD", "S6_XGA", "S6_SVGA", "S6_VGA", "S6_QVGA"
    ]
    
    for s_id in scenario_keys:
        config = SCENARIOS[s_id]
        res = run_scenario(s_id, config, video_path, detector, args)
        results.append(res)
        
    # Persiapkan teks aturan keramaian
    sepi_max = int(args.capacity * SEPI_MAX_RATIO)
    sedang_max = int(args.capacity * SEDANG_MAX_RATIO)
    target_status = classify_crowd(args.gt_person, args.capacity)['status']
    
    rules_text = (
        f"--- ATURAN KLASIFIKASI KEPADATAN (Kapasitas Maksimal: {args.capacity} orang) ---\n"
        f"- Sepi  : <= {sepi_max} orang (<= {int(SEPI_MAX_RATIO*100)}%)\n"
        f"- Sedang: {sepi_max + 1} - {sedang_max} orang ({int(SEPI_MAX_RATIO*100)+1}% - {int(SEDANG_MAX_RATIO*100)}%)\n"
        f"- Ramai : > {sedang_max} orang (> {int(SEDANG_MAX_RATIO*100)}%)\n\n"
        f"KONDISI TARGET PENGUJIAN: {args.gt_person} orang -> Seharusnya '{target_status}'\n"
    )
    print("\n" + rules_text)

    # Tampilkan Tabel Hasil di Console
    print("="*105)
    print("HASIL EVALUASI EKSPERIMEN".center(105))
    print("="*105)
    print(f"{'Skenario':<10} | {'Deskripsi':<25} | {'Avg Count':<9} | {'Prec (%)':<9} | {'Rec (%)':<9} | {'Latency (ms)':<15} | {'Acc (%)':<9}")
    print("-" * 105)
    for r in results:
        print(f"{r['Scenario']:<10} | {r['Description']:<25} | {r['Avg Count']:<9.1f} | {r['Precision (%)']:<9.2f} | {r['Recall (%)']:<9.2f} | {r['Latency (ms)']:<15.2f} | {r['Accuracy (%)']:<9.2f}")
    print("="*105)
    
    # Tulis hasil ke dalam file Markdown (hasil.md)
    hasil_path = "hasil.md"
    try:
        with open(hasil_path, "w", encoding="utf-8") as f:
            f.write("# Laporan Hasil Evaluasi Eksperimen\n\n")
            f.write(rules_text.replace("--- ATURAN", "### Aturan").replace("---", "") + "\n")
            f.write("Berikut adalah hasil pengujian metrik untuk semua skenario S1-S6:\n\n")
            f.write("| Skenario | Deskripsi | Avg Count | Precision (%) | Recall (%) | Latency (ms) | Accuracy (%) |\n")
            f.write("|----------|-----------|-----------|---------------|------------|--------------|--------------|\n")
            for r in results:
                f.write(f"| {r['Scenario']} | {r['Description']} | {r['Avg Count']:.1f} | {r['Precision (%)']:.2f} | {r['Recall (%)']:.2f} | {r['Latency (ms)']:.2f} | {r['Accuracy (%)']:.2f} |\n")
        logger.info(f"Tabel hasil pengujian berhasil disimpan di {os.path.abspath(hasil_path)}")
    except Exception as e:
        logger.error(f"Gagal menulis ke hasil.md: {e}")

if __name__ == "__main__":
    main()
