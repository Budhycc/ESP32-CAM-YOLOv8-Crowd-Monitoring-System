from ultralytics import YOLO
import torch

model = YOLO('yolov8n.pt')
print("model.device:", model.device)
print("torch.cuda.is_available():", torch.cuda.is_available())
