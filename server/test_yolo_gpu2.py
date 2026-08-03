from ultralytics import YOLO
import torch

model = YOLO('yolov8n.pt')
if torch.cuda.is_available():
    model.to('cuda')
print("model.device after to('cuda'):", model.device)
