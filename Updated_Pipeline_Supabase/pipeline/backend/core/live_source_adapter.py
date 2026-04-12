"""Live source adapter for webcam and RealSense capture backends."""

import os
import time
from threading import Lock
from typing import Any, Dict, Optional, Tuple

import cv2

try:
    from .realsense_source import RealSenseSource
    REALSENSE_SOURCE_AVAILABLE = True
except Exception:
    RealSenseSource = None
    REALSENSE_SOURCE_AVAILABLE = False


class LiveSourceAdapter:
    """Small adapter that normalizes live camera source lifecycle operations."""

    def __init__(self):
        self.lock = Lock()
        self.active_camera = None
        self.active_camera_source = 'webcam'
        self.active_camera_index = 0
        self.active_realsense_source = None
        self._webcam_probe_cache = []
        self._webcam_probe_cache_ts = 0.0
        try:
            stale_value = float(os.getenv('EDGE_REALSENSE_STALE_SECONDS', '4'))
        except Exception:
            stale_value = 4.0
        self.edge_realsense_stale_seconds = max(1.0, stale_value)
        self.edge_realsense_frame = None
        self.edge_realsense_device_name = None
        self.edge_realsense_updated_at = 0.0
        self.edge_realsense_depth_telemetry = self._default_depth_telemetry()
        self.edge_realsense_depth_preview_jpeg = None
        self.edge_realsense_capabilities = {
            'depth_stream': True,
            'color_stream': True,
            'imu': False,
            'resolution': '640x480',
            'fps': 15,
            'device_available': False,
            'sdk_available': True,
            'reason': 'No edge relay frames received yet'
        }

    @staticmethod
    def _default_depth_telemetry() -> Dict[str, Any]:
        return {
            'center_distance_m': None,
            'min_distance_m': None,
            'max_distance_m': None,
            'valid_depth_ratio': 0.0,
            'depth_available': False
        }

    def _is_edge_realsense_available_locked(self) -> bool:
        if self.edge_realsense_frame is None:
            return False
        age = time.monotonic() - float(self.edge_realsense_updated_at or 0.0)
        return age <= float(self.edge_realsense_stale_seconds)

    def _build_edge_realsense_snapshot_locked(self) -> Dict[str, Any]:
        is_available = self._is_edge_realsense_available_locked()
        age_ms = None
        if self.edge_realsense_updated_at:
            age_ms = int(max(0.0, (time.monotonic() - self.edge_realsense_updated_at) * 1000.0))

        caps = dict(self.edge_realsense_capabilities or {})
        caps['device_available'] = bool(is_available)
        caps['sdk_available'] = True
        if is_available:
            caps['reason'] = None
        elif not caps.get('reason'):
            caps['reason'] = 'Edge relay frame is stale or unavailable'

        return {
            'edge_realsense_available': bool(is_available),
            'edge_realsense_device_name': self.edge_realsense_device_name,
            'edge_realsense_age_ms': age_ms,
            'edge_realsense_capabilities': caps,
        }

    def get_edge_realsense_snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return self._build_edge_realsense_snapshot_locked()

    def ingest_edge_realsense_locked(
        self,
        frame,
        *,
        device_name: Optional[str] = None,
        depth_telemetry: Optional[Dict[str, Any]] = None,
        depth_preview_jpeg: Optional[bytes] = None,
        capabilities: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store latest edge-relayed RealSense frame/depth payload (lock must be held)."""
        self.edge_realsense_frame = frame
        self.edge_realsense_updated_at = time.monotonic()
        if device_name:
            self.edge_realsense_device_name = str(device_name).strip() or self.edge_realsense_device_name

        if isinstance(depth_telemetry, dict):
            telemetry = self._default_depth_telemetry()
            telemetry.update(depth_telemetry)
            self.edge_realsense_depth_telemetry = telemetry
        else:
            self.edge_realsense_depth_telemetry = self._default_depth_telemetry()

        if depth_preview_jpeg:
            self.edge_realsense_depth_preview_jpeg = depth_preview_jpeg

        if isinstance(capabilities, dict):
            caps = dict(self.edge_realsense_capabilities)
            caps.update(capabilities)
            self.edge_realsense_capabilities = caps

        # Keep cache fresh: while edge relay is active, do not over-probe local webcams.
        self._webcam_probe_cache_ts = time.monotonic()
        return self._build_edge_realsense_snapshot_locked()

    def _open_webcam(self, camera_index: int):
        """Open webcam with Windows-friendly backend first, then generic fallback."""
        cap = None
        if hasattr(cv2, 'CAP_DSHOW'):
            try:
                cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
            except Exception:
                cap = None

        if cap is None or not cap.isOpened():
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass
            cap = cv2.VideoCapture(camera_index)

        return cap

    def list_webcam_devices(self, max_index: int = 3, force_refresh: bool = False):
        """Probe likely webcam indexes and return openable device slots."""
        # Avoid probing every request; status endpoints can be polled frequently.
        now = time.monotonic()
        if not force_refresh and self._webcam_probe_cache and (now - self._webcam_probe_cache_ts) < 5.0:
            return list(self._webcam_probe_cache)

        # While webcam stream is active, probing other indexes can interfere with capture.
        if (
            self.active_camera_source == 'webcam'
            and self.active_camera is not None
            and self.active_camera.isOpened()
        ):
            active_only = [{'index': self.active_camera_index, 'label': f'Camera {self.active_camera_index}'}]
            self._webcam_probe_cache = list(active_only)
            self._webcam_probe_cache_ts = now
            return active_only

        devices = []
        configured_probe = os.getenv('WEBCAM_PROBE_MAX_INDEX')
        probe_seed = configured_probe if configured_probe not in (None, '') else max_index

        try:
            max_probe = int(probe_seed)
        except Exception:
            max_probe = 3

        max_probe = max(1, min(max_probe, 16))

        for idx in range(max_probe):
            cap = None
            try:
                cap = self._open_webcam(idx)
                if cap is not None and cap.isOpened():
                    devices.append({'index': idx, 'label': f'Camera {idx}'})
            except Exception:
                continue
            finally:
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass

        self._webcam_probe_cache = list(devices)
        self._webcam_probe_cache_ts = now
        return devices

    @property
    def current_source(self) -> str:
        return self.active_camera_source

    def is_active_locked(self) -> bool:
        """Return whether current source is active (lock must be held)."""
        if self.active_camera_source == 'realsense':
            return self.active_realsense_source is not None and self.active_realsense_source.pipeline is not None
        if self.active_camera_source == 'edge_realsense':
            return self._is_edge_realsense_available_locked()
        return self.active_camera is not None and self.active_camera.isOpened()

    def stop_locked(self) -> None:
        """Stop whichever source is active (lock must be held)."""
        if self.active_camera is not None:
            try:
                self.active_camera.release()
            except Exception:
                pass
            self.active_camera = None

        if self.active_realsense_source is not None:
            try:
                self.active_realsense_source.stop()
            except Exception:
                pass

        self.active_camera_source = 'webcam'
        self._webcam_probe_cache_ts = 0.0

    def _get_realsense_probe_source(self):
        if not REALSENSE_SOURCE_AVAILABLE:
            return None
        if self.active_realsense_source is not None:
            return self.active_realsense_source
        try:
            return RealSenseSource()
        except Exception:
            return None

    def get_realsense_snapshot(self) -> Dict[str, Any]:
        """Collect RealSense availability/capabilities in a uniform format."""
        source = self._get_realsense_probe_source()
        if source is None:
            return {
                'realsense_available': False,
                'realsense_device_name': None,
                'realsense_capabilities': {
                    'depth_stream': False,
                    'color_stream': False,
                    'imu': False,
                    'resolution': '640x480',
                    'fps': 60,
                    'device_available': False,
                    'sdk_available': False,
                    'reason': 'RealSense source unavailable'
                }
            }

        status = source.get_status()
        caps = source.get_capabilities()
        return {
            'realsense_available': bool(status.get('device_available')),
            'realsense_device_name': status.get('device_name'),
            'realsense_capabilities': caps
        }

    def get_default_source(self) -> str:
        snapshot = self.get_realsense_snapshot()
        if snapshot['realsense_available']:
            return 'realsense'

        edge_snapshot = self.get_edge_realsense_snapshot()
        if edge_snapshot.get('edge_realsense_available'):
            return 'edge_realsense'

        return 'webcam'

    def start_locked(self, requested_source: str, camera_index: Optional[int] = None) -> Dict[str, Any]:
        """Start requested source with graceful fallback behavior (lock must be held)."""
        source = (requested_source or 'webcam').strip().lower()
        if source not in ('webcam', 'realsense', 'edge_realsense'):
            source = 'webcam'

        fallback_to_webcam = False
        fallback_message = None

        current_camera_index = self.active_camera_index

        try:
            desired_camera_index = int(self.active_camera_index if camera_index is None else camera_index)
        except Exception:
            desired_camera_index = self.active_camera_index

        if desired_camera_index < 0:
            desired_camera_index = 0

        if self.is_active_locked() and self.active_camera_source == source:
            if source == 'webcam' and current_camera_index != desired_camera_index:
                pass
            else:
                return {
                    'success': True,
                    'source': self.active_camera_source,
                    'camera_index': self.active_camera_index if self.active_camera_source == 'webcam' else None,
                    'fallback_to_webcam': False,
                    'message': f'Live monitoring already active on {self.active_camera_source}'
                }

        self.stop_locked()

        if source == 'edge_realsense':
            if self._is_edge_realsense_available_locked():
                self.active_camera_source = 'edge_realsense'
                return {
                    'success': True,
                    'source': 'edge_realsense',
                    'camera_index': None,
                    'fallback_to_webcam': False,
                    'message': 'Live monitoring started (Edge RealSense relay)'
                }

            source = 'webcam'
            fallback_to_webcam = True
            fallback_message = 'Edge RealSense relay is unavailable or stale; switched to webcam.'

        if source == 'realsense':
            if not REALSENSE_SOURCE_AVAILABLE:
                source = 'webcam'
                fallback_to_webcam = True
                fallback_message = 'RealSense SDK is unavailable; switched to webcam.'
            else:
                try:
                    self.active_realsense_source = RealSenseSource()
                    started, error_message = self.active_realsense_source.start()
                except Exception as exc:
                    started = False
                    error_message = str(exc)

                if started:
                    self.active_camera_source = 'realsense'
                    return {
                        'success': True,
                        'source': 'realsense',
                        'camera_index': None,
                        'fallback_to_webcam': False,
                        'message': 'Live monitoring started (RealSense)'
                    }

                source = 'webcam'
                fallback_to_webcam = True
                fallback_message = f'RealSense unavailable ({error_message}); switched to webcam.'

        self.active_camera = self._open_webcam(desired_camera_index)
        opened_index = desired_camera_index
        if self.active_camera is None or not self.active_camera.isOpened():
            try:
                if self.active_camera is not None:
                    self.active_camera.release()
            except Exception:
                pass
            self.active_camera = None

            # Try any other available index to avoid hard failure on systems where index 0 is not a webcam.
            for device in self.list_webcam_devices(force_refresh=True):
                idx = int(device.get('index', -1))
                if idx < 0 or idx == desired_camera_index:
                    continue

                candidate = self._open_webcam(idx)
                if candidate is not None and candidate.isOpened():
                    self.active_camera = candidate
                    opened_index = idx
                    break

                try:
                    if candidate is not None:
                        candidate.release()
                except Exception:
                    pass

        if self.active_camera is None or not self.active_camera.isOpened():
            self.active_camera = None
            self.active_camera_index = desired_camera_index
            available_indexes = [str(d.get('index')) for d in self.list_webcam_devices(force_refresh=True)]
            available_label = ', '.join(available_indexes) if available_indexes else 'none'
            return {
                'success': False,
                'source': 'webcam',
                'camera_index': desired_camera_index,
                'fallback_to_webcam': False,
                'message': f'Failed to open webcam (requested index {desired_camera_index}; available indexes: {available_label})'
            }

        # Keep webcam buffer small to avoid stale-frame lag in annotated stream.
        try:
            self.active_camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.active_camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.active_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.active_camera.set(cv2.CAP_PROP_FPS, 30)
        except Exception:
            pass

        self.active_camera_source = 'webcam'
        self.active_camera_index = opened_index
        if fallback_to_webcam and fallback_message:
            start_message = f'{fallback_message} Using webcam index {self.active_camera_index}.'
        else:
            start_message = f'Live monitoring started (webcam index {self.active_camera_index})'

        return {
            'success': True,
            'source': 'webcam',
            'camera_index': self.active_camera_index,
            'fallback_to_webcam': bool(fallback_to_webcam),
            'message': start_message,
        }

    def read_frame_locked(self) -> Tuple[bool, Optional[Any], Optional[str]]:
        """Read one frame from current source (lock must be held)."""
        if self.active_camera_source == 'realsense':
            if self.active_realsense_source is None:
                return False, None, 'RealSense source is not initialized'
            return self.active_realsense_source.read()

        if self.active_camera_source == 'edge_realsense':
            if not self._is_edge_realsense_available_locked() or self.edge_realsense_frame is None:
                return False, None, 'Edge RealSense relay frame is unavailable or stale'
            try:
                return True, self.edge_realsense_frame.copy(), None
            except Exception:
                return True, self.edge_realsense_frame, None

        if self.active_camera is None or not self.active_camera.isOpened():
            return False, None, 'Webcam is not opened'

        ok, frame = self.active_camera.read()
        if not ok:
            return False, None, 'Failed to read webcam frame'
        return True, frame, None

    def get_depth_telemetry_locked(self) -> Dict[str, Any]:
        """Get depth telemetry for active RealSense source (lock must be held)."""
        if self.active_camera_source == 'realsense' and self.active_realsense_source is not None:
            return self.active_realsense_source.get_depth_telemetry()

        if self.active_camera_source == 'edge_realsense':
            return dict(self.edge_realsense_depth_telemetry)

        return self._default_depth_telemetry()

    def get_depth_preview_locked(self):
        """Get latest depth preview jpeg for active RealSense source (lock must be held)."""
        if self.active_camera_source == 'realsense' and self.active_realsense_source is not None:
            return self.active_realsense_source.get_depth_preview_jpeg()

        if self.active_camera_source == 'edge_realsense':
            return self.edge_realsense_depth_preview_jpeg

        return None

    def build_state_payload(self) -> Dict[str, Any]:
        """Build live state payload consumed by frontend controls."""
        with self.lock:
            is_active = self.is_active_locked()
            source = self.active_camera_source
            active_camera_index = self.active_camera_index
            edge_snapshot = self._build_edge_realsense_snapshot_locked()

        rs_snapshot = self.get_realsense_snapshot()
        if rs_snapshot['realsense_available']:
            default_source = 'realsense'
        elif edge_snapshot.get('edge_realsense_available'):
            default_source = 'edge_realsense'
        else:
            default_source = 'webcam'
        webcam_devices = self.list_webcam_devices(force_refresh=not is_active)
        return {
            'active': is_active,
            'source': source if is_active else default_source,
            'default_source': default_source,
            'camera_index': active_camera_index if source == 'webcam' else None,
            'webcam_devices': webcam_devices,
            'realsense_available': rs_snapshot['realsense_available'],
            'realsense_device_name': rs_snapshot['realsense_device_name'],
            'realsense_capabilities': rs_snapshot['realsense_capabilities'],
            'edge_realsense_available': edge_snapshot.get('edge_realsense_available', False),
            'edge_realsense_device_name': edge_snapshot.get('edge_realsense_device_name'),
            'edge_realsense_age_ms': edge_snapshot.get('edge_realsense_age_ms'),
            'edge_realsense_capabilities': edge_snapshot.get('edge_realsense_capabilities', {}),
        }
