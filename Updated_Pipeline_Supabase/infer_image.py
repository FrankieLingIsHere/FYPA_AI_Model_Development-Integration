"""
Small helper to run a single-image inference against the project's YOLO model.

Provides:
- predict_image(input_image, model_path=None, conf=0.25, imgsz=640)

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
# Readability: Module overview: keep the main setup, workflow, and fallback paths easy to scan.

from typing import Tuple, List, Union
import cv2
import numpy as np
import os
import platform
import shutil
import subprocess
from pathlib import Path
from threading import Lock, Semaphore
from typing import Any, Dict

# Default model path used in the project
# Prepare default model path for the next step.
DEFAULT_MODEL_PATH = os.path.join('Results', 'ppe_yolov86', 'weights', 'best.pt')

# Cache the model to avoid reloading
_cached_model = None
_cached_model_path = None
_cached_model_device = None
_cached_yolo_class = None
_cached_model_lock = Lock()
_cached_model_warm_paths = set()
# Prepare forced cpu reason for the next step.
_forced_cpu_reason = ''
_nvidia_gpu_hint_cache = None
_last_yolo_runtime: Dict[str, Any] = {
    'requested_device': 'auto',
    'selected_device': 'cpu',
    'selection_reason': 'not resolved yet',
    'torch_version': None,
    'cuda_available': False,
    'cuda_device_count': 0,
    'cuda_device_name': None,
    'model_loaded': False,
    'model_path': None,
    'last_error': None,
}
# Protect this step so expected failures can fall back cleanly.
try:
    # Prepare yolo predict max concurrency for the next step.
    _YOLO_PREDICT_MAX_CONCURRENCY = int(os.getenv('YOLO_PREDICT_MAX_CONCURRENCY', '1') or '1')
except (TypeError, ValueError):
    _YOLO_PREDICT_MAX_CONCURRENCY = 1
_YOLO_PREDICT_MAX_CONCURRENCY = max(1, min(_YOLO_PREDICT_MAX_CONCURRENCY, 4))
_yolo_predict_semaphore = Semaphore(_YOLO_PREDICT_MAX_CONCURRENCY)


# Section: run the env flag workflow with clear inputs and outputs.
def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    # Choose the correct branch before the workflow continues.
    if raw is None:
        # Return the prepared result to the caller.
        return bool(default)
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


# Section: run the torch runtime info workflow with clear inputs and outputs.
def _torch_runtime_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        'torch_version': None,
        'cuda_available': False,
        'cuda_device_count': 0,
        'cuda_device_name': None,
        'error': None,
    }
    # Protect this step so expected failures can fall back cleanly.
    try:
        import torch

        # Prepare values needed by the next step.
        info['torch_version'] = getattr(torch, '__version__', None)
        cuda_available = bool(torch.cuda.is_available())
        info['cuda_available'] = cuda_available
        if cuda_available:
            # Prepare device count for the next step.
            device_count = int(torch.cuda.device_count())
            info['cuda_device_count'] = device_count
            if device_count > 0:
                # Prepare values needed by the next step.
                info['cuda_device_name'] = torch.cuda.get_device_name(0)
    except Exception as exc:
        # Prepare values needed by the next step.
        info['error'] = str(exc)
    # Return the prepared result to the caller.
    return info


# Section: run the detect nvidia gpu hint workflow with clear inputs and outputs.
def _detect_nvidia_gpu_hint() -> Dict[str, Any]:
    global _nvidia_gpu_hint_cache
    if _nvidia_gpu_hint_cache is not None:
        return dict(_nvidia_gpu_hint_cache)

    payload = {'detected': False, 'name': None, 'method': None}

    # Prepare nvidia smi for the next step.
    nvidia_smi = shutil.which('nvidia-smi')
    if nvidia_smi:
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare completed for the next step.
            completed = subprocess.run(
                [nvidia_smi, '-L'],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            output = (completed.stdout or '').strip()
            if completed.returncode == 0 and output:
                # Prepare payload for the next step.
                payload = {'detected': True, 'name': output.splitlines()[0][:180], 'method': 'nvidia-smi'}
                _nvidia_gpu_hint_cache = payload
                return dict(payload)
        except Exception:
            pass

    # Choose the correct branch before the workflow continues.
    if platform.system().lower() == 'windows':
        # Prepare ps for the next step.
        ps = shutil.which('powershell') or shutil.which('pwsh')
        if ps:
            # Protect this step so expected failures can fall back cleanly.
            try:
                # Prepare completed for the next step.
                completed = subprocess.run(
                    [
                        ps,
                        '-NoProfile',
                        '-ExecutionPolicy',
                        'Bypass',
                        '-Command',
                        (
                            "Get-CimInstance Win32_VideoController | "
                            "Where-Object { $_.Name -match 'NVIDIA' } | "
                            "Select-Object -First 1 -ExpandProperty Name"
                        ),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                # Prepare name for the next step.
                name = (completed.stdout or '').strip()
                if completed.returncode == 0 and name:
                    # Prepare payload for the next step.
                    payload = {'detected': True, 'name': name.splitlines()[0][:180], 'method': 'win32_video_controller'}
            except Exception:
                pass

    # Prepare nvidia gpu hint cache for the next step.
    _nvidia_gpu_hint_cache = payload
    return dict(payload)


# Section: run the resolve yolo device workflow with clear inputs and outputs.
def _resolve_yolo_device() -> Tuple[str, Dict[str, Any]]:
    """Choose a safe YOLO runtime device without requiring CUDA on every host."""
    global _last_yolo_runtime

    requested = str(os.getenv('YOLO_DEVICE') or os.getenv('LOCAL_YOLO_DEVICE') or 'auto').strip().lower()
    # Prepare requested for the next step.
    requested = requested or 'auto'
    torch_info = _torch_runtime_info()

    selected = 'cpu'
    reason = ''

    if _forced_cpu_reason:
        # Prepare selected for the next step.
        selected = 'cpu'
        reason = f'forced CPU fallback after device error: {_forced_cpu_reason}'
    # Choose the correct branch before the workflow continues.
    elif requested in ('cpu', 'none', 'off'):
        selected = 'cpu'
        reason = 'CPU explicitly requested'
    elif requested in ('auto', 'gpu', 'cuda', 'cuda:0'):
        if torch_info.get('cuda_available') and int(torch_info.get('cuda_device_count') or 0) > 0:
            # Prepare selected for the next step.
            selected = 'cuda:0'
            reason = 'CUDA-capable Torch detected'
        else:
            selected = 'cpu'
            reason = 'CUDA unavailable in current Torch runtime'
    # Choose the correct branch before the workflow continues.
    elif requested.isdigit():
        # Choose the correct branch before the workflow continues.
        if torch_info.get('cuda_available') and int(requested) < int(torch_info.get('cuda_device_count') or 0):
            selected = f'cuda:{int(requested)}'
            reason = f'CUDA device {requested} requested'
        else:
            # Prepare selected for the next step.
            selected = 'cpu'
            reason = f'CUDA device {requested} requested but unavailable'
    elif requested.startswith('cuda:'):
        try:
            requested_idx = int(requested.split(':', 1)[1])
        except Exception:
            requested_idx = 0
        # Choose the correct branch before the workflow continues.
        if torch_info.get('cuda_available') and requested_idx < int(torch_info.get('cuda_device_count') or 0):
            selected = f'cuda:{requested_idx}'
            # Prepare reason for the next step.
            reason = f'CUDA device {requested_idx} requested'
        else:
            selected = 'cpu'
            reason = f'{requested} requested but unavailable'
    else:
        selected = 'cpu'
        reason = f"Unsupported YOLO_DEVICE={requested!r}; using CPU"

    # Prepare last yolo runtime for the next step.
    _last_yolo_runtime = {
        **_last_yolo_runtime,
        'requested_device': requested,
        'selected_device': selected,
        'selection_reason': reason,
        'torch_version': torch_info.get('torch_version'),
        'cuda_available': bool(torch_info.get('cuda_available')),
        'cuda_device_count': int(torch_info.get('cuda_device_count') or 0),
        'cuda_device_name': torch_info.get('cuda_device_name'),
        'torch_error': torch_info.get('error'),
    }
    # Return the prepared result to the caller.
    return selected, dict(_last_yolo_runtime)


# Section: run the mark yolo device error workflow with clear inputs and outputs.
def _mark_yolo_device_error(device: str, exc: Exception) -> None:
    """Latch CPU fallback after a CUDA/device failure so report generation continues."""
    global _forced_cpu_reason, _last_yolo_runtime

    message = str(exc)
    _forced_cpu_reason = f'{device}: {message[:240]}'
    # Prepare last yolo runtime for the next step.
    _last_yolo_runtime = {
        **_last_yolo_runtime,
        'selected_device': 'cpu',
        'selection_reason': f'forced CPU fallback after device error: {_forced_cpu_reason}',
        'last_error': message,
    }


# Section: run the get yolo runtime diagnostics workflow with clear inputs and outputs.
def get_yolo_runtime_diagnostics() -> Dict[str, Any]:
    """Return current YOLO device/runtime details for local-mode diagnostics."""
    # Prepare values needed by the next step.
    selected_device, payload = _resolve_yolo_device()
    gpu_hint = _detect_nvidia_gpu_hint()
    torch_install_recommendation = None
    with _cached_model_lock:
        # Trigger the side effect required for this stage.
        payload.update({
            'selected_device': selected_device,
            'model_loaded': _cached_model is not None,
            'model_path': _cached_model_path,
            'model_device': _cached_model_device,
            'nvidia_gpu_detected': bool(gpu_hint.get('detected')),
            'nvidia_gpu_name': gpu_hint.get('name'),
            'nvidia_gpu_detection_method': gpu_hint.get('method'),
            'torch_install_recommendation': torch_install_recommendation,
            'cpu_fallback_latched': bool(_forced_cpu_reason),
            'cpu_fallback_reason': _forced_cpu_reason or None,
        })
    # Return the prepared result to the caller.
    return payload


# Section: run the get yolo class workflow with clear inputs and outputs.
def _get_yolo_class():
    """Import YOLO lazily so lightweight tests can import this module without torch startup."""
    global _cached_yolo_class
    if _cached_yolo_class is not None:
        # Return the prepared result to the caller.
        return _cached_yolo_class

    # Protect this step so expected failures can fall back cleanly.
    try:
        from ultralytics import YOLO as _YOLO
    except Exception as exc:
        raise RuntimeError(
            "Ultralytics YOLO is unavailable. Install runtime vision dependencies "
            "or avoid calling predict_image in lightweight fallback/status tests."
        ) from exc

    _cached_yolo_class = _YOLO
    # Return the prepared result to the caller.
    return _cached_yolo_class


# Section: run the ensure model loaded workflow with clear inputs and outputs.
def _ensure_model_loaded(resolved_model_path: str, device: str = None):
    """Load and cache the YOLO model once per resolved weights path."""
    global _cached_model, _cached_model_path, _cached_model_device, _last_yolo_runtime

    selected_device = device or _resolve_yolo_device()[0]

    # Open the managed resource only for the block that needs it.
    with _cached_model_lock:
        # Choose the correct branch before the workflow continues.
        if (
            _cached_model is None
            or _cached_model_path != resolved_model_path
            or _cached_model_device != selected_device
        ):
            # Prepare yolo class for the next step.
            yolo_class = _get_yolo_class()
            model = yolo_class(resolved_model_path)
            if selected_device and selected_device != 'cpu' and hasattr(model, 'to'):
                # Trigger the side effect required for this stage.
                model.to(selected_device)
            _cached_model = model
            _cached_model_path = resolved_model_path
            _cached_model_device = selected_device
            _cached_model_warm_paths.discard((resolved_model_path, selected_device))
            _last_yolo_runtime = {
                **_last_yolo_runtime,
                'model_loaded': True,
                'model_path': resolved_model_path,
                'model_device': selected_device,
                'last_error': None,
            }

        # Return the prepared result to the caller.
        return _cached_model


# Section: run the resolve model path workflow with clear inputs and outputs.
def resolve_model_path(model_path: str = None) -> str:
    """Resolve YOLO weights path across local/hosted working-directory layouts."""
    # Prepare script dir for the next step.
    script_dir = Path(__file__).resolve().parent
    nested_default = Path('Updated_Pipeline_Supabase') / DEFAULT_MODEL_PATH

    explicit_env_path = os.getenv('YOLO_MODEL_PATH', '').strip()
    candidate_strings = [
        model_path or '',
        explicit_env_path,
        DEFAULT_MODEL_PATH,
        str(nested_default),
    ]

    # Prepare candidates for the next step.
    candidates = []
    for raw in candidate_strings:
        # Choose the correct branch before the workflow continues.
        if not raw:
            continue
        path_obj = Path(raw)
        if path_obj.is_absolute():
            # Trigger the side effect required for this stage.
            candidates.append(path_obj)
        else:
            candidates.append(Path.cwd() / path_obj)
            candidates.append(script_dir / path_obj)
            candidates.append(script_dir.parent / path_obj)
            candidates.append(script_dir.parent / 'Updated_Pipeline_Supabase' / path_obj)

    # Prepare seen for the next step.
    seen = set()
    unique_candidates = []
    for candidate in candidates:
        # Prepare normalized for the next step.
        normalized = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_candidates.append(candidate)

    # Process each item in this collection using the same rule set.
    for candidate in unique_candidates:
        if candidate.exists() and candidate.is_file():
            # Return the prepared result to the caller.
            return str(candidate)

    searched = '\n'.join(f"- {str(c)}" for c in unique_candidates)
    raise FileNotFoundError(
        "YOLO model weights not found. Set YOLO_MODEL_PATH or place weights at one of:\n"
        f"{searched}"
    )


# Section: run the read image workflow with clear inputs and outputs.
def _read_image(input_image: Union[str, bytes, np.ndarray]):
    """Read various input types and return a BGR numpy array or raise ValueError."""
    # Choose the correct branch before the workflow continues.
    if isinstance(input_image, np.ndarray):
        # assume already BGR (OpenCV style) or RGB; we'll treat as BGR
        # Return the prepared result to the caller.
        return input_image
    if isinstance(input_image, str):
        img = cv2.imread(input_image)
        if img is None:
            # Surface the failure with enough context for the caller.
            raise ValueError(f"Could not read image from path: {input_image}")
        return img
    if isinstance(input_image, (bytes, bytearray)):
        arr = np.frombuffer(input_image, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        # Choose the correct branch before the workflow continues.
        if img is None:
            raise ValueError("Could not decode image from bytes")
        return img
    # Surface the failure with enough context for the caller.
    raise ValueError("input_image must be path (str), bytes, or numpy.ndarray")


# Section: run the is model ready workflow with clear inputs and outputs.
def is_model_ready(model_path: str = None) -> bool:
    """Return whether the requested YOLO weights are already loaded in memory."""
    global _cached_model, _cached_model_path, _cached_model_device

    if _cached_model is None or _cached_model_path is None:
        # Return the prepared result to the caller.
        return False

    # Prepare resolved model path for the next step.
    resolved_model_path = resolve_model_path(model_path)
    selected_device, _ = _resolve_yolo_device()
    return str(_cached_model_path) == str(resolved_model_path) and _cached_model_device == selected_device


# Section: run the warmup model workflow with clear inputs and outputs.
def warmup_model(
    model_path: str = None,
    conf: float = 0.25,
    imgsz: int = 640,
) -> str:
    """Load the YOLO weights and run a tiny dummy inference once."""
    # Prepare resolved model path for the next step.
    resolved_model_path = resolve_model_path(model_path)
    selected_device, _ = _resolve_yolo_device()

    with _cached_model_lock:
        # Choose the correct branch before the workflow continues.
        if (resolved_model_path, selected_device) in _cached_model_warm_paths:
            # Return the prepared result to the caller.
            return resolved_model_path

    try:
        model = _ensure_model_loaded(resolved_model_path, selected_device)
    except Exception as exc:
        if selected_device != 'cpu' and _env_flag('YOLO_ALLOW_CPU_FALLBACK', True):
            _mark_yolo_device_error(selected_device, exc)
            selected_device = 'cpu'
            model = _ensure_model_loaded(resolved_model_path, selected_device)
        else:
            # Surface the failure with enough context for the caller.
            raise

    # Prepare dummy for the next step.
    dummy = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)
    try:
        # Trigger the side effect required for this stage.
        model.predict(dummy, imgsz=imgsz, conf=conf, iou=0.45, half=False, device=selected_device, verbose=False)
    except Exception as exc:
        if selected_device != 'cpu' and _env_flag('YOLO_ALLOW_CPU_FALLBACK', True):
            _mark_yolo_device_error(selected_device, exc)
            selected_device = 'cpu'
            # Prepare model for the next step.
            model = _ensure_model_loaded(resolved_model_path, selected_device)
            model.predict(dummy, imgsz=imgsz, conf=conf, iou=0.45, half=False, device=selected_device, verbose=False)
        else:
            raise

    # Open the managed resource only for the block that needs it.
    with _cached_model_lock:
        # Trigger the side effect required for this stage.
        _cached_model_warm_paths.add((resolved_model_path, selected_device))

    return resolved_model_path


# Section: run the predict image workflow with clear inputs and outputs.
def predict_image(input_image: Union[str, bytes, np.ndarray],
                  model_path: str = None,
                  conf: float = 0.25,
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
    # Prepare img for the next step.
    img = _read_image(input_image)

    resolved_model_path = resolve_model_path(model_path)
    selected_device, _ = _resolve_yolo_device()
    try:
        # Prepare model for the next step.
        model = _ensure_model_loaded(resolved_model_path, selected_device)
    except Exception as exc:
        if selected_device != 'cpu' and _env_flag('YOLO_ALLOW_CPU_FALLBACK', True):
            # Trigger the side effect required for this stage.
            _mark_yolo_device_error(selected_device, exc)
            selected_device = 'cpu'
            model = _ensure_model_loaded(resolved_model_path, selected_device)
        else:
            raise

    # Ensure image is in uint8 format (not float)
    # Choose the correct branch before the workflow continues.
    if img.dtype != np.uint8:
        img = img.astype(np.uint8)

    # perform prediction with half=False to avoid dtype mismatch
    # Note: Default conf=0.25 reduces false positives (especially hardhat/hair confusion)
    # Can be overridden by caller if needed, but 0.25 is recommended for PPE detection
    _yolo_predict_semaphore.acquire()
    try:
        try:
            # Prepare results for the next step.
            results = model.predict(
                img,
                imgsz=imgsz,
                conf=conf,
                iou=0.45,
                half=False,
                device=selected_device,
                verbose=False,
            )
        except Exception as exc:
            # Choose the correct branch before the workflow continues.
            if selected_device != 'cpu' and _env_flag('YOLO_ALLOW_CPU_FALLBACK', True):
                # Trigger the side effect required for this stage.
                _mark_yolo_device_error(selected_device, exc)
                selected_device = 'cpu'
                model = _ensure_model_loaded(resolved_model_path, selected_device)
                results = model.predict(
                    img,
                    imgsz=imgsz,
                    conf=conf,
                    iou=0.45,
                    half=False,
                    device=selected_device,
                    verbose=False,
                )
            else:
                # Surface the failure with enough context for the caller.
                raise
    finally:
        # Trigger the side effect required for this stage.
        _yolo_predict_semaphore.release()
    # Prepare detections for the next step.
    detections = []
    annotated = img.copy()

    if len(results) == 0:
        return detections, annotated

    res = results[0]
    if not hasattr(res, 'boxes') or len(res.boxes) == 0:
        # Return the prepared result to the caller.
        return detections, annotated

    # Prepare boxes for the next step.
    boxes = res.boxes
    xyxy = boxes.xyxy.cpu().numpy() if hasattr(boxes, 'xyxy') else np.array([])
    confs = boxes.conf.cpu().numpy() if hasattr(boxes, 'conf') else np.array([])
    clses = boxes.cls.cpu().numpy().astype(int) if hasattr(boxes, 'cls') else np.array([])

    # color palette
    palette = [(0,255,0), (0,0,255), (255,0,0), (0,255,255), (255,0,255), (255,255,0)]

    names = []
    # Choose the correct branch before the workflow continues.
    if isinstance(model.names, dict):
        # dict mapping may not be positional; build list by sorted keys
        # Prepare names for the next step.
        names = [model.names[k] for k in sorted(model.names.keys())]
    else:
        names = list(model.names)

    for i, (bb, sc, cls_id) in enumerate(zip(xyxy, confs, clses)):
        x1, y1, x2, y2 = map(int, bb)
        class_name = names[int(cls_id)] if int(cls_id) < len(names) else str(cls_id)
        det = {'bbox': [x1, y1, x2, y2], 'score': float(sc), 'class_name': class_name, 'class_id': int(cls_id)}
        detections.append(det)

        # draw on annotated image
        # Prepare color for the next step.
        color = palette[i % len(palette)]
        cv2.rectangle(annotated, (x1,y1), (x2,y2), color, 2)
        label = f"{class_name} {sc:.2f}"
        t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
        cv2.rectangle(annotated, (x1, y1 - t_size[1] - 6), (x1 + t_size[0] + 6, y1), color, -1)
        cv2.putText(annotated, label, (x1 + 3, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1, cv2.LINE_AA)

    # Return the prepared result to the caller.
    return detections, annotated


# Choose the correct branch before the workflow continues.
if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        # Trigger the side effect required for this stage.
        print('Usage: python infer_image.py path/to/image.jpg')
        sys.exit(1)
    img_path = sys.argv[1]
    # Prepare values needed by the next step.
    dets, img = predict_image(img_path)
    print('Detections:')
    for d in dets:
        print(d)
    # show annotated image
    try:
        # Trigger the side effect required for this stage.
        cv2.imshow('Inference', img)
        print('Press any key in the image window to close...')
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    except Exception:
        print('Unable to show image window (headless?). Exiting.')
