import cv2
import numpy as np
import logging
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
                    logger.info(f"Exporting {model_path} to OpenVINO format (may take a minute)...")
                    temp_model = YOLO(model_path)
                    temp_model.export(format='openvino')
                
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

    def process_frame(self, image_bytes: bytes, draw_overlay: bool = True, crowd_status: str = "Sepi"):
        """
        Decodes JPEG bytes, runs YOLOv8 inference, filters 'person' class,
        and annotates the image.
        
        Returns:
        - person_count (int)
        - avg_confidence (float)
        - boxes (list of dicts with bbox coords)
        - annotated_frame_bytes (bytes JPEG)
        """
        # 1. Decode JPEG image bytes into OpenCV matrix (BGR format)
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            logger.error("Failed to decode image bytes into OpenCV frame.")
            return 0, 0.0, [], None

        # 2. Run inference with YOLOv8 model
        results = self.model(frame, conf=CONFIDENCE_THRESHOLD, device=self.inference_device, verbose=False)[0]

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

        # Return original image_bytes directly (saves ~15ms CPU re-encoding overhead per frame)
        return person_count, avg_confidence, detected_persons, image_bytes, latency_ms
