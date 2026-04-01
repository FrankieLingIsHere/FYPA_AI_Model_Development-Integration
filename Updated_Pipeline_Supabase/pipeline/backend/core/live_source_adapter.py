"""Live source adapter for webcam and RealSense capture backends."""

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
        self.active_realsense_source = None

    @property
    def current_source(self) -> str:
        return self.active_camera_source

    def is_active_locked(self) -> bool:
        """Return whether current source is active (lock must be held)."""
        if self.active_camera_source == 'realsense':
            return self.active_realsense_source is not None and self.active_realsense_source.pipeline is not None
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
        return 'realsense' if snapshot['realsense_available'] else 'webcam'

    def start_locked(self, requested_source: str) -> Dict[str, Any]:
        """Start requested source with graceful fallback behavior (lock must be held)."""
        source = (requested_source or 'webcam').strip().lower()
        if source not in ('webcam', 'realsense'):
            source = 'webcam'

        if self.is_active_locked() and self.active_camera_source == source:
            return {
                'success': True,
                'source': self.active_camera_source,
                'fallback_to_webcam': False,
                'message': f'Live monitoring already active on {self.active_camera_source}'
            }

        self.stop_locked()

        if source == 'realsense':
            if not REALSENSE_SOURCE_AVAILABLE:
                source = 'webcam'
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
                        'fallback_to_webcam': False,
                        'message': 'Live monitoring started (RealSense)'
                    }

                source = 'webcam'
                fallback_message = f'RealSense unavailable ({error_message}); switched to webcam.'

        self.active_camera = cv2.VideoCapture(0)
        if not self.active_camera.isOpened():
            self.active_camera = None
            return {
                'success': False,
                'source': 'webcam',
                'fallback_to_webcam': False,
                'message': 'Failed to open webcam'
            }

        self.active_camera_source = 'webcam'
        return {
            'success': True,
            'source': 'webcam',
            'fallback_to_webcam': source != 'webcam',
            'message': 'Live monitoring started (webcam)' if source == 'webcam' else fallback_message
        }

    def read_frame_locked(self) -> Tuple[bool, Optional[Any], Optional[str]]:
        """Read one frame from current source (lock must be held)."""
        if self.active_camera_source == 'realsense':
            if self.active_realsense_source is None:
                return False, None, 'RealSense source is not initialized'
            return self.active_realsense_source.read()

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
        return {
            'center_distance_m': None,
            'min_distance_m': None,
            'max_distance_m': None,
            'valid_depth_ratio': 0.0,
            'depth_available': False
        }

    def get_depth_preview_locked(self):
        """Get latest depth preview jpeg for active RealSense source (lock must be held)."""
        if self.active_camera_source != 'realsense' or self.active_realsense_source is None:
            return None
        return self.active_realsense_source.get_depth_preview_jpeg()

    def build_state_payload(self) -> Dict[str, Any]:
        """Build live state payload consumed by frontend controls."""
        with self.lock:
            is_active = self.is_active_locked()
            source = self.active_camera_source

        rs_snapshot = self.get_realsense_snapshot()
        default_source = 'realsense' if rs_snapshot['realsense_available'] else 'webcam'
        return {
            'active': is_active,
            'source': source if is_active else default_source,
            'default_source': default_source,
            'camera_index': 0 if is_active and source == 'webcam' else None,
            'realsense_available': rs_snapshot['realsense_available'],
            'realsense_device_name': rs_snapshot['realsense_device_name'],
            'realsense_capabilities': rs_snapshot['realsense_capabilities']
        }
