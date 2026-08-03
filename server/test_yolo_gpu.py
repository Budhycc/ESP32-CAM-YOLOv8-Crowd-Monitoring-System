from ultralytics import YOLO
import torch

model = YOLO('yolov8n.pt')
print("model.device before inference:", model.device)
res = model(torch.zeros(1, 3, 64, 64), verbose=False)
print("model.device after inference:", model.device)
