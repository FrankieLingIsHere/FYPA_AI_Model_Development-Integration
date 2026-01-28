"""
Live PPE Compliance Detection with Intel RealSense D435i
========================================================
Real-time PPE detection using YOLOv8 with RealSense camera support.
Displays RGB detection feed alongside 2D depth visualization.
Falls back to standard webcam if RealSense is not available.
"""

from ultralytics import YOLO
import cv2
import numpy as np
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import RealSense camera module
from realsense_camera import RealSenseCamera, create_combined_view

# Load your best model
model = YOLO('Results/ppe_yolov86/weights/best.pt')

# Define a function to check for overlap between two bounding boxes (IoU)
def calculate_iou(boxA, boxB):
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    iou = interArea / float(boxAArea + boxBArea - interArea) if (boxAArea + boxBArea - interArea) > 0 else 0
    return iou


# Project class names
PROJECT_CLASSES = [
    'Gloves', 'No-Gloves',
    'Goggles', 'No-Goggles',
    'Hardhat', 'No-Hardhat',
    'Mask', 'No-Mask',
    'Safety Vest', 'No-Safety Vest',
    'Person'
]

# Initialize RealSense camera (with webcam fallback)
# RealSense D435i is primary, standard webcam is fallback
camera = RealSenseCamera(width=640, height=480, fps=30, enable_depth=True)
if not camera.open():
    raise RuntimeError('Could not open camera (RealSense or webcam)')

# Display camera info
camera_info = camera.get_camera_info()
print("\n" + "=" * 60)
print("CAMERA CONFIGURATION")
print("=" * 60)
for key, value in camera_info.items():
    print(f"  {key}: {value}")
print("=" * 60 + "\n")

# Helper to normalize class names for robust matching
def _norm(name: str) -> str:
    # ensure we operate on strings (model.names may be dict keys or non-str)
    s = str(name)
    return ''.join(ch for ch in s.lower() if ch.isalnum())

# Build normalized -> canonical mapping
norm_project = { _norm(c): c for c in PROJECT_CLASSES }

# Try to find close project name from a normalized source name
def find_project_name(norm_name: str) -> str:
    # exact
    if norm_name in norm_project:
        return norm_project[norm_name]
    # substring / prefix heuristics
    for pnorm, pc in norm_project.items():
        if pnorm in norm_name or norm_name in pnorm:
            return pc
    # no good match
    return None

# Colors for drawing (one per project class)
COLOR_MAP = {}
import random
random.seed(42)
for cls in PROJECT_CLASSES:
    COLOR_MAP[cls] = tuple(int(x) for x in np.array([random.randint(0,255) for _ in range(3)]))

DEBUG = True
if DEBUG:
    # model.names can be a dict or list; build a stable list for printing
    if isinstance(model.names, dict):
        names_list = [model.names[k] for k in sorted(model.names.keys())]
    else:
        names_list = list(model.names)
    print('Model class list:')
    for i, n in enumerate(names_list):
        print(f'  id={i} name="{n}" norm="{_norm(n)}"')
    print('\nStarting live inference with RealSense D435i.')
    print('Press Q to quit.')
    print('=' * 60)

frame_count = 0
while True:
    # Read from RealSense camera (or webcam fallback)
    ret, color_frame, depth_raw, depth_colormap = camera.read()
    if not ret or color_frame is None:
        print('Frame read failed, exiting')
        break
    
    frame_count += 1
    frame = color_frame.copy()

    # Run model on the color frame
    results = model.predict(frame, imgsz=640, conf=0.25, iou=0.45, verbose=False)
    # results is a list; take first element
    if len(results) == 0:
        # Create combined view even with no detections
        combined = create_combined_view(color_frame, depth_colormap, frame)
        cv2.imshow('PPE Live - RealSense D435i', combined)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        continue

    res = results[0]
    person_boxes = []
    ppe_boxes = {c: [] for c in PROJECT_CLASSES if c != 'Person'}

    if hasattr(res, 'boxes') and len(res.boxes) > 0:
        boxes = res.boxes
        xyxy = boxes.xyxy.cpu().numpy() if hasattr(boxes, 'xyxy') else np.array([])
        confs = boxes.conf.cpu().numpy() if hasattr(boxes, 'conf') else np.array([])
        clses = boxes.cls.cpu().numpy().astype(int) if hasattr(boxes, 'cls') else np.array([])

        for bb, conf, cls in zip(xyxy, confs, clses):
            x1, y1, x2, y2 = map(int, bb)
            src_name = model.names[int(cls)]
            norm = _norm(src_name)
            # Map to project name using exact norm or heuristics
            mapped = find_project_name(norm)
            if mapped is None:
                # fallback to original src_name if nothing matches
                target_name = src_name
            else:
                target_name = mapped

            # store boxes for later logic
            if target_name == 'Person' or _norm(target_name) == _norm('Person'):
                person_boxes.append((x1,y1,x2,y2, conf, target_name))
            else:
                ppe_boxes.setdefault(target_name, []).append((x1,y1,x2,y2, conf, target_name))

            # Draw box and label for all mapped classes
            color = COLOR_MAP.get(target_name, (0,255,0))
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            label = f"{target_name} {conf:.2f}"
            t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
            cv2.rectangle(frame, (x1, y1 - t_size[1] - 6), (x1 + t_size[0] + 6, y1), color, -1)
            cv2.putText(frame, label, (x1 + 3, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1, cv2.LINE_AA)

    # Add status info to detection frame
    status_text = f"Frame: {frame_count} | Persons: {len(person_boxes)}"
    cv2.putText(frame, status_text, (10, frame.shape[0] - 10), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # Create combined view with RGB detections and depth map side by side
    combined = create_combined_view(color_frame, depth_colormap, frame)
    
    cv2.imshow('PPE Live - RealSense D435i', combined)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

camera.release()
cv2.destroyAllWindows()
print(f"\nSession ended. Total frames processed: {frame_count}")
