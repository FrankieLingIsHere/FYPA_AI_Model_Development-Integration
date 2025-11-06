
import os
import json
import matplotlib.pyplot as plt
import seaborn as sns
import albumentations as A
from ultralytics import YOLO
from sklearn.metrics import confusion_matrix, classification_report
import cv2

def main():
    # Paths
    DATA_YAML = os.path.join('data', 'combined_data.yaml')
    RESULTS_DIR = 'Results'
    METRICS_JSON = os.path.join(RESULTS_DIR, 'test_metrics.json')

    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Model setup
    model = YOLO('yolov8s.pt')  # Use YOLOv8 nano for speed; change to yolov8s.pt for higher accuracy

    # Training with augmentation and regularization
    results = model.train(
        data=DATA_YAML,
        epochs=80,
        imgsz=640,
        device=0,  # Use GPU
        project=RESULTS_DIR,
        name='ppe_yolov8_augmented',
        batch=16,
        optimizer='Adam',
        augment=True,  # Enable built-in augmentation
        dropout=0.2,   # Regularization
        mosaic=0.5,   # Strong augmentation with 50% probability
        hsv_h=0.015,   # Color augmentation (hue)
        hsv_s=0.7,     # Color augmentation (saturation)
        hsv_v=0.4,     # Color augmentation (value)
        degrees=20,    # Rotation
        scale=0.6,     # Scaling
        shear=5,       # Shear
        perspective=0.001, # Perspective
        flipud=0.5,    # Flip vertically with 50% probability
        fliplr=0.5,    # Flip horizontally with 50% probability
        mixup=0.5,     # MixUp augmentation with 50% probability
        copy_paste=0.5 # Copy-paste augmentation with 50% probability
    )

    # Plot loss curves
    metrics_path = os.path.join(RESULTS_DIR, 'ppe_yolov8', 'results.csv')
    if os.path.exists(metrics_path):
        import pandas as pd
        df = pd.read_csv(metrics_path)
        plt.figure(figsize=(10,5))
        plt.plot(df['epoch'], df['train/box_loss'], label='Train Box Loss')
        plt.plot(df['epoch'], df['val/box_loss'], label='Val Box Loss')
        plt.plot(df['epoch'], df['train/cls_loss'], label='Train Cls Loss')
        plt.plot(df['epoch'], df['val/cls_loss'], label='Val Cls Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.legend()
        plt.title('Loss Curves')
        plt.savefig(os.path.join(RESULTS_DIR, 'loss_curves.png'))
        plt.close()

    # Evaluate on test set
    metrics = model.val(data=DATA_YAML, split='test', batch=16, device=0)

    # Confusion matrix
    if hasattr(metrics, 'confusion_matrix'):
        cm = metrics.confusion_matrix
        plt.figure(figsize=(8,6))
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues')
        plt.title('Confusion Matrix')
        plt.xlabel('Predicted')
        plt.ylabel('True')
        plt.savefig(os.path.join(RESULTS_DIR, 'confusion_matrix.png'))
        plt.close()

    # Save test metrics as JSON
    with open(METRICS_JSON, 'w') as f:
        json.dump(metrics.results_dict, f, indent=2)

    print(f"Training complete. Results saved in {RESULTS_DIR}")


if __name__ == "__main__":
    main()
