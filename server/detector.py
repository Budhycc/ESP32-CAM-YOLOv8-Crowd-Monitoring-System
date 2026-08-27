import cv2
import numpy as np
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from ultralytics import YOLO
from config import YOLO_MODEL_PATH, CONFIDENCE_THRESHOLD, TARGET_CLASS_ID

logger = logging.getLogger("YOLOv8Detector")

class ObjectDetector:
    def __init__(self, model_path: str = YOLO_MODEL_PATH):
        """Initializes and loads the YOLOv8 model ONCE at startup."""
        import os
        model_path = os.path.abspath(model_path)
        logger.info(f"Loading YOLOv8 model from '{model_path}'...")
        import torch
        
        if torch.cuda.is_available():
            self.model = YOLO(model_path)
            self.device = "CUDA"
            self.inference_device = "0"
        else:
            try:
                import openvino as ov
                ov_model_path = model_path.replace('.pt', '_openvino_model')
                
                if not os.path.exists(ov_model_path):
                    logger.info(f"Exporting {model_path} to OpenVINO format with imgsz=416 (may take a minute)...")
                    temp_model = YOLO(model_path)
                    # imgsz=416: compile model dengan static shape [1,3,416,416]
                    # HARUS sama dengan imgsz yang dipakai saat inference
                    # Hapus folder yolov8n_openvino_model jika ingin ganti imgsz
                    temp_model.export(format='openvino', imgsz=416)
                
                self.model = YOLO(ov_model_path)
                core = ov.Core()
                if "GPU" in core.available_devices:
                    self.device = "OpenVINO (Intel iGPU)"
                    self.inference_device = "gpu"
                else:
                    self.device = "OpenVINO (Intel CPU)"
                    self.inference_device = "cpu"
                    
            except ImportError:
                self.model = YOLO(model_path)
                self.device = "CPU"
                self.inference_device = "cpu"
                logger.warning("OpenVINO not installed. Using standard CPU fallback.")

        logger.info(f"YOLOv8 model loaded successfully on {self.device}.")
        
        # Dedicated thread pool untuk inference: max 4 thread agar tidak explosion
        # saat banyak kamera streaming bersamaan
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="yolo_worker")
        logger.info("ThreadPoolExecutor (max_workers=4) initialized for inference.")
        
        # State for Frame Averaging (keyed by camera_id), menggunakan deque O(1) vs list.pop(0) O(n)
        self.history = {}
        
        # CLAHE objek diinisialisasi sekali (bukan per-frame) untuk menghindari alokasi berulang
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def process_frame(
        self, 
        image_bytes: bytes, 
        draw_overlay: bool = True, 
        crowd_status: str = "Sepi", 
        use_clahe: bool = False,
        camera_id: str = "default",
        use_frame_averaging: bool = False,
        use_adaptive_confidence: bool = False
    ):
        """
        Decodes JPEG bytes, optionally applies CLAHE, runs YOLOv8 inference, 
        filters 'person' class, and annotates the image.
        
        Returns tuple of 5 values (always):
        - person_count (int)
        - avg_confidence (float)
        - boxes (list of dicts with bbox coords)
        - annotated_frame_bytes (bytes JPEG)
        - latency_ms (float)
        """
        try:
            # 1. Decode JPEG image bytes into OpenCV matrix (BGR format)
            # "Corrupt JPEG data" warning dari OpenCV adalah NORMAL untuk frame terpotong WiFi
            # dan tidak selalu berarti frame tidak bisa digunakan
            try:
                nparr = np.frombuffer(image_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            except Exception:
                return 0, 0.0, [], image_bytes, 0.0, None

            if frame is None:
                # PENTING: harus return 6 nilai agar tidak ValueError saat unpack di main.py
                # "Corrupt JPEG" warning dari OpenCV di atas adalah normal untuk frame terpotong
                logger.warning("Failed to decode JPEG frame — skipping this frame.")
                return 0, 0.0, [], image_bytes, 0.0, None

            if use_clahe:
                # Aplikasikan CLAHE pada channel Lightness (reuse objek self.clahe, tidak alokasi baru per-frame)
                lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
                l_channel, a, b = cv2.split(lab)
                cl = self.clahe.apply(l_channel)
                limg = cv2.merge((cl, a, b))
                frame = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

            current_conf = CONFIDENCE_THRESHOLD
            
            # Adaptive Confidence Threshold
            if use_adaptive_confidence:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                mean_brightness = np.mean(gray)
                # Jika rata-rata brightness di bawah 100 (redup), turunkan threshold sebesar 0.1
                if mean_brightness < 100:
                    current_conf = max(0.1, current_conf - 0.1)

            # 2. Run inference dengan YOLOv8 model
            # imgsz=416: YOLO resize internal ke 416x416 sebelum inference
            # Meningkatkan kecepatan ~25-35% vs auto-detect dari frame VGA (640x480)
            # Akurasi deteksi orang di jarak normal tetap baik di resolusi ini
            results = self.model(
                frame,
                conf=current_conf,
                device=self.inference_device,
                imgsz=416,
                verbose=False
            )[0]

            detected_persons = []
            confidences = []

            # 3. Extract bounding boxes and filter for target class (person: ID 0)
            for box in results.boxes:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())

                if cls_id == TARGET_CLASS_ID:
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    detected_persons.append({
                        "bbox": [x1, y1, x2, y2],
                        "confidence": round(conf, 2)
                    })
                    confidences.append(conf)

            person_count = len(detected_persons)
            
            # Frame Averaging menggunakan deque(maxlen=3): append/pop O(1) vs list.pop(0) O(n)
            if use_frame_averaging:
                if camera_id not in self.history:
                    self.history[camera_id] = deque(maxlen=3)
                self.history[camera_id].append(person_count)
                person_count = int(round(sum(self.history[camera_id]) / len(self.history[camera_id])))

            avg_confidence = float(np.mean(confidences)) if confidences else 0.0

            latency_ms = results.speed['preprocess'] + results.speed['inference'] + results.speed['postprocess']

            # Return original image_bytes langsung (hemat ~15ms vs re-encode ulang)
            # frame (numpy array) juga dikembalikan agar caller dapat reuse tanpa decode ulang
            return person_count, avg_confidence, detected_persons, image_bytes, latency_ms, frame

        except Exception as e:
            logger.error(f"Unexpected error during YOLOv8 inference: {e}", exc_info=True)
            return 0, 0.0, [], image_bytes, 0.0, None
