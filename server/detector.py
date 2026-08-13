import cv2
import numpy as np
import logging
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

    def process_frame(self, image_bytes: bytes, draw_overlay: bool = True, crowd_status: str = "Sepi"):
        """
        Decodes JPEG bytes, runs YOLOv8 inference, filters 'person' class,
        and annotates the image.
        
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
                return 0, 0.0, [], image_bytes, 0.0

            if frame is None:
                # PENTING: harus return 5 nilai (bukan 4) agar tidak ValueError saat unpack di main.py
                # "Corrupt JPEG" warning dari OpenCV di atas adalah normal untuk frame terpotong
                logger.warning("Failed to decode JPEG frame — skipping this frame.")
                return 0, 0.0, [], image_bytes, 0.0

            # 2. Run inference dengan YOLOv8 model
            # imgsz=416: YOLO resize internal ke 416x416 sebelum inference
            # Meningkatkan kecepatan ~25-35% vs auto-detect dari frame VGA (640x480)
            # Akurasi deteksi orang di jarak normal tetap baik di resolusi ini
            results = self.model(
                frame,
                conf=CONFIDENCE_THRESHOLD,
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
            avg_confidence = float(np.mean(confidences)) if confidences else 0.0

            latency_ms = results.speed['preprocess'] + results.speed['inference'] + results.speed['postprocess']

            # Return original image_bytes langsung (hemat ~15ms vs re-encode ulang)
            return person_count, avg_confidence, detected_persons, image_bytes, latency_ms

        except Exception as e:
            logger.error(f"Unexpected error during YOLOv8 inference: {e}", exc_info=True)
            return 0, 0.0, [], image_bytes, 0.0
