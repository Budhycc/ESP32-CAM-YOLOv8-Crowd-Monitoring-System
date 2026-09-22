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

def get_dynamic_gt(current_sec, video_name="2.mp4"):
    """
    Pemetaan Ground Truth dinamis berdasarkan detik ke-sekian dari video.
    Mendukung pemetaan untuk 1.mp4 (60 detik) dan 2.mp4 (40 detik).
    """
    if "1.mp4" in video_name:
        if current_sec <= 6: return 5
        elif current_sec <= 20: return 4
        elif current_sec <= 22: return 5
        elif current_sec <= 32: return 4
        else: return 3
    else:
        # Default untuk 2.mp4
        if current_sec <= 5: return 12
        elif current_sec <= 15: return 14
        elif current_sec <= 17: return 15
        elif current_sec <= 26: return 14
        elif current_sec <= 29: return 13
        else: return 12

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

def run_scenario(scenario_id, config, video_paths, detector, args):
    logger.info(f"--- Memulai {scenario_id}: Resolusi {config['name']} {config['resolution']} ---")
    
    precisions = []
    recalls = []
    latencies = []
    counts = []
    correct_classifications = 0
    frames_processed = 0
    
    # Pelacakan per kondisi
    cond_metrics = {
        "Sepi": {"prec": [], "rec": [], "lat": [], "cnt": [], "corr": 0, "frames": 0},
        "Sedang": {"prec": [], "rec": [], "lat": [], "cnt": [], "corr": 0, "frames": 0},
        "Ramai": {"prec": [], "rec": [], "lat": [], "cnt": [], "corr": 0, "frames": 0}
    }
    
    for video_path in video_paths:
        video_name = os.path.basename(video_path)
        if "1.mp4" in video_name:
            duration = 60
        elif "2.mp4" in video_name:
            duration = 40
        else:
            duration = 40
            
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Gagal membuka video {video_path}")
            continue
            
        # Simulasi FPS
        target_fps = config.get("fps", 10)
        interval_sec = 1.0 / target_fps
        
        current_simulated_time = 0.0
        
        while current_simulated_time < duration:
            # PENTING: Pompa event GUI di baris PERTAMA loop agar tidak pernah macet
            if cv2.waitKey(1) & 0xFF == ord('q'):
                logger.info("Pengujian dihentikan secara manual (tombol Q ditekan).")
                cap.release()
                cv2.destroyAllWindows()
                sys.exit(0)
                
            # Langsung loncat ke detik yang dituju di video
            cap.set(cv2.CAP_PROP_POS_MSEC, current_simulated_time * 1000)
            ret, raw_frame = cap.read()
            
            if not ret:
                break # Video habis
                
            # Resize sesuai resolusi skenario
            w, h = config['resolution']
            raw_frame = cv2.resize(raw_frame, (w, h))
            

            # Simulasikan kompresi dan transmisi JPEG seperti ESP32-CAM
            ok, encoded = cv2.imencode(".jpg", raw_frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                current_simulated_time += interval_sec
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
            
            # Dapatkan Ground Truth dinamis berdasarkan detik simulasi
            current_gt = get_dynamic_gt(current_simulated_time, video_name)
            expected_status = classify_crowd(current_gt, args.capacity)["status"]
            
            prec, rec = calculate_metrics(person_count, current_gt)
            precisions.append(prec)
            recalls.append(rec)
            latencies.append(end_to_end_latency_ms)
            counts.append(person_count)
            
            # Catat ke tracker per kondisi
            c_m = cond_metrics[expected_status]
            c_m["prec"].append(prec)
            c_m["rec"].append(rec)
            c_m["lat"].append(end_to_end_latency_ms)
            c_m["cnt"].append(person_count)
            c_m["frames"] += 1
            is_correct = (classification["status"] == expected_status)
            if is_correct:
                c_m["corr"] += 1
                correct_classifications += 1
                
            frames_processed += 1
            
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
                    cv2.putText(annotated_frame, f"Skenario: {scenario_id} | Res: {config['name']} | Target FPS: {target_fps}", 
                                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                    cv2.putText(annotated_frame, f"Sim Time: {current_simulated_time:.1f}s | Count: {person_count} / GT: {current_gt} | Prec: {prec * 100:.1f}% | Rec: {rec * 100:.1f}%", 
                                (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    cv2.putText(annotated_frame, f"Latency E2E: {end_to_end_latency_ms:.1f} ms", 
                                (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                    cv2.putText(annotated_frame, f"Status: {classification['status']} (Target: {expected_status})", 
                                (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                    
                    cv2.imshow("Experiment Bounding Box", annotated_frame)
                    cv2.waitKey(1)
                    
            # Tambahkan waktu simulasi
            current_simulated_time += interval_sec

        cap.release()

    cv2.destroyAllWindows()
    
    avg_precision = np.mean(precisions) * 100 if precisions else 0.0
    avg_recall = np.mean(recalls) * 100 if recalls else 0.0
    avg_latency = np.mean(latencies) if latencies else 0.0
    avg_count = np.mean(counts) if counts else 0.0
    accuracy_rate = (correct_classifications / frames_processed) * 100 if frames_processed > 0 else 0.0
    
    logger.info(f"Hasil {scenario_id}: Count={avg_count:.1f}, Prec={avg_precision:.1f}%, Rec={avg_recall:.1f}%, Acc={accuracy_rate:.1f}%")
    
    return {
        "Scenario": scenario_id,
        "Description": f"{config['name']} ({'Mitigasi' if config['clahe'] else 'Tanpa Mitigasi'})",
        "Avg Count": avg_count,
        "Expected Status": "Dinamis",
        "Precision (%)": avg_precision,
        "Recall (%)": avg_recall,
        "Latency (ms)": avg_latency,
        "Accuracy (%)": accuracy_rate,
        "Condition_Metrics": cond_metrics
    }

def main():
    parser = argparse.ArgumentParser(description="Script Evaluasi Eksperimen S1-S6 (Dinamis - Multi Video)")
    parser.add_argument("--video_dir", type=str, default="sample/", help="Direktori yang berisi video-video pengujian (default: folder sample/)")
    parser.add_argument("--capacity", type=int, default=15, help="Kapasitas ruangan untuk klasifikasi status (default: 15)")
    
    args = parser.parse_args()
    
    video_dir = args.video_dir
    import glob
    video_paths = []
    if os.path.isdir(video_dir):
        for ext in ["*.mp4", "*.avi", "*.mov"]:
            video_paths.extend(glob.glob(os.path.join(video_dir, ext)))
            
    if not video_paths:
        logger.error(f"Tidak ada file video yang ditemukan di folder {video_dir}!")
        sys.exit(1)
        
    video_paths.sort() # Urutkan agar 1.mp4 jalan duluan, lalu 2.mp4
    video_names = [os.path.basename(vp) for vp in video_paths]
    logger.info(f"Video terdeteksi untuk digabung: {', '.join(video_names)}")
        
    logger.info("Inisialisasi Model YOLOv8 (tunggu sebentar)...")
    detector = ObjectDetector()
    
    logger.info("Melakukan pemanasan AI (Warmup) agar Windows tidak hang...")
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", dummy_frame)
    detector.process_frame(image_bytes=encoded.tobytes())
    logger.info("Pemanasan selesai! Memulai simulasi.")
    
    results = []
    
    # Jalankan Skenario S1 s/d S6 secara berurutan
    scenario_keys = [
        "S1", "S2", "S3", "S4", 
        "S5_HD", "S5_XGA", "S5_SVGA", "S5_VGA", "S5_QVGA",
        "S6_HD", "S6_XGA", "S6_SVGA", "S6_VGA", "S6_QVGA"
    ]
    
    for s_id in scenario_keys:
        config = SCENARIOS[s_id]
        res = run_scenario(s_id, config, video_paths, detector, args)
        results.append(res)
        
    # Persiapkan teks aturan keramaian
    sepi_max = int(args.capacity * SEPI_MAX_RATIO)
    sedang_max = int(args.capacity * SEDANG_MAX_RATIO)
    
    rules_text = (
        f"--- ATURAN KLASIFIKASI KEPADATAN (Kapasitas Maksimal: {args.capacity} orang) ---\n"
        f"- Sepi  : <= {sepi_max} orang (<= {int(SEPI_MAX_RATIO*100)}%)\n"
        f"- Sedang: {sepi_max + 1} - {sedang_max} orang ({int(SEPI_MAX_RATIO*100)+1}% - {int(SEDANG_MAX_RATIO*100)}%)\n"
        f"- Ramai : > {sedang_max} orang (> {int(SEDANG_MAX_RATIO*100)}%)\n\n"
        f"KONDISI TARGET PENGUJIAN: Dinamis (Sesuai detik berjalannya video)\n"
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
    
    # Tulis hasil ke dalam file Markdown dengan nama gabungan
    hasil_path = "hasil.md"
    try:
        with open(hasil_path, "w", encoding="utf-8") as f:
            f.write(f"# Laporan Hasil Evaluasi Eksperimen (Gabungan Multi-Video)\n\n")
            f.write(rules_text.replace("--- ATURAN", "### Aturan").replace("---", "") + "\n")
            
            def write_table(group_name, items):
                if not items:
                    return
                f.write(f"### {group_name}\n\n")
                f.write("| Skenario | Kategori (Resolusi) | Avg Count | Precision (%) | Recall (%) | Latency (ms) | Accuracy (%) |\n")
                f.write("|----------|---------------------|-----------|---------------|------------|--------------|--------------|\n")
                
                sum_count = sum_prec = sum_rec = sum_lat = sum_acc = 0
                for r in items:
                    desc = r['Description'].replace(" (Tanpa Mitigasi)", "").replace(" (Mitigasi)", "").replace(" + Mitigasi", "")
                    f.write(f"| {r['Scenario']} | {desc} | {r['Avg Count']:.1f} | {r['Precision (%)']:.2f} | {r['Recall (%)']:.2f} | {r['Latency (ms)']:.2f} | {r['Accuracy (%)']:.2f} |\n")
                    sum_count += r['Avg Count']
                    sum_prec += r['Precision (%)']
                    sum_rec += r['Recall (%)']
                    sum_lat += r['Latency (ms)']
                    sum_acc += r['Accuracy (%)']
                
                n = len(items)
                f.write(f"| **Rata-Rata** | **Seluruh Kategori** | **{sum_count/n:.1f}** | **{sum_prec/n:.2f}** | **{sum_rec/n:.2f}** | **{sum_lat/n:.2f}** | **{sum_acc/n:.2f}** |\n\n")

            s1_s4 = [r for r in results if r['Scenario'] in ["S1", "S2", "S3", "S4"]]
            s5 = [r for r in results if r['Scenario'].startswith("S5")]
            s6 = [r for r in results if r['Scenario'].startswith("S6")]
            
            write_table("Skenario 1-4 (Baseline Kondisi Cahaya & Keramaian)", s1_s4)
            write_table("Skenario 5 (Uji Resolusi Tanpa Mitigasi Algoritma)", s5)
            write_table("Skenario 6 (Uji Resolusi DENGAN Mitigasi Algoritma)", s6)
            
            # --- Agregasi dan Tulis Tabel Rata-rata Per Kondisi ---
            f.write("### Rata-Rata Metrik Berdasarkan Kondisi Ruangan (Keseluruhan Pengujian)\n\n")
            f.write("| Kondisi Asli (Ground Truth) | Avg Count | Precision (%) | Recall (%) | Latency (ms) | Accuracy (%) |\n")
            f.write("|-----------------------------|-----------|---------------|------------|--------------|--------------|\n")
            
            overall_cond = {
                "Sepi": {"prec": [], "rec": [], "lat": [], "cnt": [], "corr": 0, "frames": 0},
                "Sedang": {"prec": [], "rec": [], "lat": [], "cnt": [], "corr": 0, "frames": 0},
                "Ramai": {"prec": [], "rec": [], "lat": [], "cnt": [], "corr": 0, "frames": 0}
            }
            
            for r in results:
                cm = r["Condition_Metrics"]
                for cond in ["Sepi", "Sedang", "Ramai"]:
                    overall_cond[cond]["prec"].extend(cm[cond]["prec"])
                    overall_cond[cond]["rec"].extend(cm[cond]["rec"])
                    overall_cond[cond]["lat"].extend(cm[cond]["lat"])
                    overall_cond[cond]["cnt"].extend(cm[cond]["cnt"])
                    overall_cond[cond]["corr"] += cm[cond]["corr"]
                    overall_cond[cond]["frames"] += cm[cond]["frames"]
                    
            for cond in ["Sepi", "Sedang", "Ramai"]:
                c_data = overall_cond[cond]
                if c_data["frames"] > 0:
                    a_prec = np.mean(c_data["prec"]) * 100
                    a_rec = np.mean(c_data["rec"]) * 100
                    a_lat = np.mean(c_data["lat"])
                    a_cnt = np.mean(c_data["cnt"])
                    a_acc = (c_data["corr"] / c_data["frames"]) * 100
                    f.write(f"| **{cond}** | {a_cnt:.1f} | {a_prec:.2f} | {a_rec:.2f} | {a_lat:.2f} | {a_acc:.2f} |\n")
                else:
                    f.write(f"| **{cond}** | N/A | N/A | N/A | N/A | N/A |\n")
            
        logger.info(f"Tabel hasil pengujian berhasil disimpan di {os.path.abspath(hasil_path)}")
    except Exception as e:
        logger.error(f"Gagal menulis ke hasil.md: {e}")

if __name__ == "__main__":
    main()
