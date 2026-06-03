# Readability: Module overview: keep the main setup, workflow, and fallback paths easy to scan.
from ultralytics import YOLO
import cv2
import numpy as np

# Load your best model
# Prepare model for the next step.
model = YOLO('Results/ppe_yolov86/weights/best.pt')

# Define a function to check for overlap between two bounding boxes (IoU)
# Section: run the calculate iou workflow with clear inputs and outputs.
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
    'Hardhat', 'No-Hardhat',
    'Mask', 'No-Mask',
    'Safety Vest', 'No-Safety Vest',
    'Person'
]

# Run real-time inference on the webcam
# Start webcam capture and run per-frame inference + drawing
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    raise RuntimeError('Could not open webcam (device 0)')

# Helper to normalize class names for robust matching
# Section: run the norm workflow with clear inputs and outputs.
def _norm(name: str) -> str:
    # ensure we operate on strings (model.names may be dict keys or non-str)
    s = str(name)
    return ''.join(ch for ch in s.lower() if ch.isalnum())

# Build normalized -> canonical mapping
norm_project = { _norm(c): c for c in PROJECT_CLASSES }

# Try to find close project name from a normalized source name
# Section: run the find project name workflow with clear inputs and outputs.
def find_project_name(norm_name: str) -> str:
    # exact
    if norm_name in norm_project:
        # Return the prepared result to the caller.
        return norm_project[norm_name]
    # substring / prefix heuristics
    for pnorm, pc in norm_project.items():
        if pnorm in norm_name or norm_name in pnorm:
            return pc
    # no good match
    return None

# Colors for drawing (one per project class)
# Prepare color map for the next step.
COLOR_MAP = {}
import random
random.seed(42)
for cls in PROJECT_CLASSES:
    # Prepare values needed by the next step.
    COLOR_MAP[cls] = tuple(int(x) for x in np.array([random.randint(0,255) for _ in range(3)]))

DEBUG = True
if DEBUG:
    # model.names can be a dict or list; build a stable list for printing
    if isinstance(model.names, dict):
        # Prepare names list for the next step.
        names_list = [model.names[k] for k in sorted(model.names.keys())]
    else:
        names_list = list(model.names)
    # Trigger the side effect required for this stage.
    print('Model class list:')
    for i, n in enumerate(names_list):
        print(f'  id={i} name="{n}" norm="{_norm(n)}"')
    print('Starting live inference. Press q to quit.')
# Keep the loop active only while the runtime condition is true.
while True:
    ret, frame = cap.read()
    if not ret:
        # Trigger the side effect required for this stage.
        print('Frame read failed, exiting')
        break

    # Run model on the frame
    # Prepare results for the next step.
    results = model.predict(frame, imgsz=640, conf=0.25, iou=0.45)
    # results is a list; take first element
    if len(results) == 0:
        cv2.imshow('PPE Live', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        continue

    res = results[0]
    # Prepare person boxes for the next step.
    person_boxes = []
    ppe_boxes = {c: [] for c in PROJECT_CLASSES if c != 'Person'}

    if hasattr(res, 'boxes') and len(res.boxes) > 0:
        # Prepare boxes for the next step.
        boxes = res.boxes
        xyxy = boxes.xyxy.cpu().numpy() if hasattr(boxes, 'xyxy') else np.array([])
        confs = boxes.conf.cpu().numpy() if hasattr(boxes, 'conf') else np.array([])
        clses = boxes.cls.cpu().numpy().astype(int) if hasattr(boxes, 'cls') else np.array([])

        for bb, conf, cls in zip(xyxy, confs, clses):
            # Prepare values needed by the next step.
            x1, y1, x2, y2 = map(int, bb)
            src_name = model.names[int(cls)]
            norm = _norm(src_name)
            # Map to project name using exact norm or heuristics
            mapped = find_project_name(norm)
            if mapped is None:
                # fallback to original src_name if nothing matches
                # Prepare target name for the next step.
                target_name = src_name
                if DEBUG:
                    print(f"[DEBUG] No project mapping for '{src_name}' (norm='{norm}'), using source name")
            else:
                target_name = mapped
                if DEBUG and _norm(target_name) != norm:
                    print(f"[DEBUG] Mapped '{src_name}' (norm={norm}) -> '{target_name}'")

            # Choose the correct branch before the workflow continues.
            if DEBUG:
                # Trigger the side effect required for this stage.
                print(f"[DETECT] cls={cls} src='{src_name}' norm='{norm}' mapped='{target_name}' conf={conf:.2f}")

            # store boxes for later logic
            if target_name == 'Person' or _norm(target_name) == _norm('Person'):
                person_boxes.append((x1,y1,x2,y2, conf, target_name))
            else:
                ppe_boxes.setdefault(target_name, []).append((x1,y1,x2,y2, conf, target_name))

            # Draw box and label for all mapped classes
            # Prepare color for the next step.
            color = COLOR_MAP.get(target_name, (0,255,0))
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            label = f"{target_name} {conf:.2f}"
            t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
            cv2.rectangle(frame, (x1, y1 - t_size[1] - 6), (x1 + t_size[0] + 6, y1), color, -1)
            cv2.putText(frame, label, (x1 + 3, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1, cv2.LINE_AA)

    # Optional: print counts per frame
    # Trigger the side effect required for this stage.
    print('--- New Frame ---')
    print(f'Found {len(person_boxes)} persons.')
    for ppe_item, items in ppe_boxes.items():
        # Trigger the side effect required for this stage.
        print(f'Found {len(items)} of {ppe_item}')

    cv2.imshow('PPE Live', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Trigger the side effect required for this stage.
cap.release()
cv2.destroyAllWindows()
