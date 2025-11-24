"""
Small helper to run a single-image inference against the project's YOLO model.

Provides:
- predict_image(input_image, model_path=None, conf=0.10, imgsz=640)

Input:
- input_image: either a file path (str), bytes, or a numpy.ndarray (BGR or RGB).
- model_path: optional path to the model weights. Defaults to the project best.pt.
- conf: minimum confidence threshold (default 0.10).
- imgsz: image size for inference.

Output (tuple): (detections, annotated_image)
- detections: list of dicts: {'bbox': [x1,y1,x2,y2], 'score': float, 'class_name': str, 'class_id': int}
- annotated_image: numpy.ndarray (BGR) with drawn boxes and labels. Not saved to disk.

Usage examples:
>>> from infer_image import predict_image
>>> dets, img = predict_image('test.jpg')
>>> print(dets)

Run as CLI:
python infer_image.py path/to/image.jpg

"""

from typing import Tuple, List, Union
import cv2
import numpy as np
from ultralytics import YOLO
import os

# Default model path used in the project
DEFAULT_MODEL_PATH = os.path.join('Results', 'ppe_yolov86', 'weights', 'best.pt')

# Cache the model to avoid reloading
_cached_model = None
_cached_model_path = None


def _read_image(input_image: Union[str, bytes, np.ndarray]):
    """Read various input types and return a BGR numpy array or raise ValueError."""
    if isinstance(input_image, np.ndarray):
        # assume already BGR (OpenCV style) or RGB; we'll treat as BGR
        return input_image
    if isinstance(input_image, str):
        img = cv2.imread(input_image)
        if img is None:
            raise ValueError(f"Could not read image from path: {input_image}")
        return img
    if isinstance(input_image, (bytes, bytearray)):
        arr = np.frombuffer(input_image, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image from bytes")
        return img
    raise ValueError("input_image must be path (str), bytes, or numpy.ndarray")


def predict_image(input_image: Union[str, bytes, np.ndarray],
                  model_path: str = None,
                  conf: float = 0.10,
                  imgsz: int = 640) -> Tuple[List[dict], np.ndarray]:
    """Run inference on a single image and return detections + annotated image.

    Contract:
    - Loads YOLO model from `model_path` or project's default.
    - Returns detections list and annotated BGR image.
    - Does not write any files.

    Edge cases:
    - Raises ValueError for unreadable inputs.
    - If no detections, returns an empty list and the original image.
    """
    global _cached_model, _cached_model_path
    
    img = _read_image(input_image)

    if model_path is None:
        model_path = DEFAULT_MODEL_PATH

    # Use cached model if same path, otherwise load new one
    if _cached_model is None or _cached_model_path != model_path:
        _cached_model = YOLO(model_path)
        _cached_model_path = model_path

    model = _cached_model

    # Ensure image is in uint8 format (not float)
    if img.dtype != np.uint8:
        img = img.astype(np.uint8)

    # perform prediction with half=False to avoid dtype mismatch
    results = model.predict(img, imgsz=imgsz, conf=conf, iou=0.45, half=False, verbose=False)
    detections = []
    annotated = img.copy()

    if len(results) == 0:
        return detections, annotated

    res = results[0]
    if not hasattr(res, 'boxes') or len(res.boxes) == 0:
        return detections, annotated

    boxes = res.boxes
    xyxy = boxes.xyxy.cpu().numpy() if hasattr(boxes, 'xyxy') else np.array([])
    confs = boxes.conf.cpu().numpy() if hasattr(boxes, 'conf') else np.array([])
    clses = boxes.cls.cpu().numpy().astype(int) if hasattr(boxes, 'cls') else np.array([])

    # color palette
    palette = [(0,255,0), (0,0,255), (255,0,0), (0,255,255), (255,0,255), (255,255,0)]

    names = []
    if isinstance(model.names, dict):
        # dict mapping may not be positional; build list by sorted keys
        names = [model.names[k] for k in sorted(model.names.keys())]
    else:
        names = list(model.names)

    for i, (bb, sc, cls_id) in enumerate(zip(xyxy, confs, clses)):
        x1, y1, x2, y2 = map(int, bb)
        class_name = names[int(cls_id)] if int(cls_id) < len(names) else str(cls_id)
        det = {'bbox': [x1, y1, x2, y2], 'score': float(sc), 'class_name': class_name, 'class_id': int(cls_id)}
        detections.append(det)

        # draw on annotated image
        color = palette[i % len(palette)]
        cv2.rectangle(annotated, (x1,y1), (x2,y2), color, 2)
        label = f"{class_name} {sc:.2f}"
        t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
        cv2.rectangle(annotated, (x1, y1 - t_size[1] - 6), (x1 + t_size[0] + 6, y1), color, -1)
        cv2.putText(annotated, label, (x1 + 3, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1, cv2.LINE_AA)

    return detections, annotated


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: python infer_image.py path/to/image.jpg')
        sys.exit(1)
    img_path = sys.argv[1]
    dets, img = predict_image(img_path)
    print('Detections:')
    for d in dets:
        print(d)
    # show annotated image
    try:
        cv2.imshow('Inference', img)
        print('Press any key in the image window to close...')
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    except Exception:
        print('Unable to show image window (headless?). Exiting.')
