"""Live source adapter for webcam and RealSense capture backends."""
# Readability: Backend core: coordinate detection, persistence, and report workflow concerns.

import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional, Tuple

import cv2

# Protect this step so expected failures can fall back cleanly.
try:
    from .realsense_source import RealSenseSource
    # Prepare realsense source available for the next step.
    REALSENSE_SOURCE_AVAILABLE = True
except Exception:
    RealSenseSource = None
    REALSENSE_SOURCE_AVAILABLE = False


# Section: group live source adapter state and behaviour in one readable unit.
class LiveSourceAdapter:
    """Small adapter that normalizes live camera source lifecycle operations."""

    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self):
        # Prepare lock for the next step.
        self.lock = Lock()
        self.active_camera = None
        self.active_camera_source = 'webcam'
        self.active_camera_index = 0
        self.active_realsense_source = None
        self._webcam_probe_cache = []
        self._webcam_probe_cache_ts = 0.0
        self._backend_fail_until: Dict[Tuple[int, str], float] = {}
        self._preferred_backend_by_index: Dict[int, str] = {}
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare probe cache seconds for the next step.
            probe_cache_seconds = float(os.getenv('WEBCAM_PROBE_CACHE_SECONDS', '15'))
        except Exception:
            probe_cache_seconds = 15.0
        self.webcam_probe_cache_seconds = max(2.0, probe_cache_seconds)
        try:
            negative_probe_cache_seconds = float(os.getenv('WEBCAM_NEGATIVE_PROBE_CACHE_SECONDS', '90'))
        except Exception:
            negative_probe_cache_seconds = 90.0
        # Prepare webcam negative probe cache seconds for the next step.
        self.webcam_negative_probe_cache_seconds = max(
            self.webcam_probe_cache_seconds,
            min(negative_probe_cache_seconds, 600.0)
        )
        try:
            # Prepare backend fail cooldown for the next step.
            backend_fail_cooldown = float(os.getenv('WEBCAM_BACKEND_FAIL_COOLDOWN_SECONDS', '180'))
        except Exception:
            backend_fail_cooldown = 180.0
        self.webcam_backend_fail_cooldown_seconds = max(5.0, min(backend_fail_cooldown, 1800.0))
        # Prepare last good camera index path for the next step.
        self.last_good_camera_index_path = Path(
            os.getenv(
                'WEBCAM_LAST_GOOD_INDEX_FILE',
                str(Path.home() / '.casm_local_state' / 'last_webcam_index.txt')
            )
        )
        self.active_camera_index = self._load_last_good_camera_index(default_index=self.active_camera_index)
        try:
            # Prepare read retry attempts for the next step.
            read_retry_attempts = int(os.getenv('WEBCAM_READ_RETRY_ATTEMPTS', '5'))
        except Exception:
            read_retry_attempts = 5
        # Prepare webcam read retry attempts for the next step.
        self.webcam_read_retry_attempts = max(1, min(read_retry_attempts, 20))
        try:
            warmup_attempts = int(os.getenv('WEBCAM_START_WARMUP_ATTEMPTS', '4'))
        except Exception:
            warmup_attempts = 4
        self.webcam_start_warmup_attempts = max(1, min(warmup_attempts, 20))
        try:
            # Prepare warmup sleep for the next step.
            warmup_sleep = float(os.getenv('WEBCAM_START_WARMUP_SLEEP_SECONDS', '0.06'))
        except Exception:
            warmup_sleep = 0.06
        # Prepare webcam start warmup sleep seconds for the next step.
        self.webcam_start_warmup_sleep_seconds = max(0.0, min(warmup_sleep, 0.5))
        try:
            stale_value = float(os.getenv('EDGE_REALSENSE_STALE_SECONDS', '4'))
        except Exception:
            stale_value = 4.0
        self.edge_realsense_stale_seconds = max(1.0, stale_value)
        self.edge_realsense_frame = None
        self.edge_realsense_device_name = None
        self.edge_realsense_updated_at = 0.0
        # Prepare edge realsense depth telemetry for the next step.
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

    # Section: run the allow realsense webcam fallback workflow with clear inputs and outputs.
    @staticmethod
    def _allow_realsense_webcam_fallback() -> bool:
        """Whether explicit RealSense selections may silently fall back to webcam."""
        # Return the prepared result to the caller.
        return str(os.getenv('LIVE_REALSENSE_ALLOW_WEBCAM_FALLBACK', 'false')).strip().lower() in (
            '1',
            'true',
            'yes',
            'on',
        )

    # Section: run the load last good camera index workflow with clear inputs and outputs.
    def _load_last_good_camera_index(self, default_index: int = 0) -> int:
        try:
            # Choose the correct branch before the workflow continues.
            if self.last_good_camera_index_path.exists():
                # Prepare value for the next step.
                value = int(self.last_good_camera_index_path.read_text(encoding='utf-8').strip())
                return max(0, value)
        except Exception:
            pass
        # Return the prepared result to the caller.
        return max(0, int(default_index or 0))

    # Section: run the persist last good camera index workflow with clear inputs and outputs.
    def _persist_last_good_camera_index(self, camera_index: int) -> None:
        try:
            # Trigger the side effect required for this stage.
            self.last_good_camera_index_path.parent.mkdir(parents=True, exist_ok=True)
            self.last_good_camera_index_path.write_text(str(max(0, int(camera_index))), encoding='utf-8')
        except Exception:
            pass

    # Section: run the backend label workflow with clear inputs and outputs.
    @staticmethod
    def _backend_label(backend: Optional[int]) -> str:
        # Choose the correct branch before the workflow continues.
        if backend is None:
            return 'any'
        if hasattr(cv2, 'CAP_DSHOW') and backend == cv2.CAP_DSHOW:
            # Return the prepared result to the caller.
            return 'dshow'
        if hasattr(cv2, 'CAP_MSMF') and backend == cv2.CAP_MSMF:
            return 'msmf'
        return str(backend)

    # Section: run the is backend suppressed workflow with clear inputs and outputs.
    def _is_backend_suppressed(self, camera_index: int, backend_label: str) -> bool:
        # Prepare key for the next step.
        key = (int(camera_index), str(backend_label))
        until_epoch = float(self._backend_fail_until.get(key, 0.0) or 0.0)
        if until_epoch <= 0:
            # Return the prepared result to the caller.
            return False
        if time.monotonic() >= until_epoch:
            self._backend_fail_until.pop(key, None)
            return False
        return True

    # Section: run the mark backend failure workflow with clear inputs and outputs.
    def _mark_backend_failure(self, camera_index: int, backend_label: str) -> None:
        # Prepare key for the next step.
        key = (int(camera_index), str(backend_label))
        self._backend_fail_until[key] = time.monotonic() + float(self.webcam_backend_fail_cooldown_seconds)

    # Section: run the mark backend success workflow with clear inputs and outputs.
    def _mark_backend_success(self, camera_index: int, backend_label: str) -> None:
        key = (int(camera_index), str(backend_label))
        self._backend_fail_until.pop(key, None)
        self._preferred_backend_by_index[int(camera_index)] = str(backend_label)

    # Section: run the read webcam frame with retries workflow with clear inputs and outputs.
    def _read_webcam_frame_with_retries(
        self,
        cap,
        *,
        attempts: Optional[int] = None,
        delay_seconds: float = 0.0,
    ) -> Tuple[bool, Optional[Any]]:
        # Choose the correct branch before the workflow continues.
        if cap is None or not cap.isOpened():
            # Return the prepared result to the caller.
            return False, None

        max_attempts = self.webcam_read_retry_attempts if attempts is None else int(attempts)
        max_attempts = max(1, min(max_attempts, 30))
        wait_s = max(0.0, float(delay_seconds or 0.0))

        for attempt in range(max_attempts):
            try:
                # Prepare values needed by the next step.
                ok, frame = cap.read()
            except Exception:
                ok, frame = False, None

            # Choose the correct branch before the workflow continues.
            if ok and frame is not None:
                return True, frame

            if wait_s > 0 and attempt < (max_attempts - 1):
                time.sleep(wait_s)

        # Return the prepared result to the caller.
        return False, None

    # Section: run the is webcam capture ready workflow with clear inputs and outputs.
    def _is_webcam_capture_ready(self, cap, *, attempts: Optional[int] = None) -> bool:
        ok, _ = self._read_webcam_frame_with_retries(
            cap,
            attempts=attempts if attempts is not None else self.webcam_start_warmup_attempts,
            delay_seconds=self.webcam_start_warmup_sleep_seconds,
        )
        return bool(ok)

    # Section: run the default depth telemetry workflow with clear inputs and outputs.
    @staticmethod
    def _default_depth_telemetry() -> Dict[str, Any]:
        # Return the prepared result to the caller.
        return {
            'center_distance_m': None,
            'min_distance_m': None,
            'max_distance_m': None,
            'valid_depth_ratio': 0.0,
            'depth_available': False
        }

    # Section: run the is edge realsense available locked workflow with clear inputs and outputs.
    def _is_edge_realsense_available_locked(self) -> bool:
        # Choose the correct branch before the workflow continues.
        if self.edge_realsense_frame is None:
            # Return the prepared result to the caller.
            return False
        age = time.monotonic() - float(self.edge_realsense_updated_at or 0.0)
        return age <= float(self.edge_realsense_stale_seconds)

    # Section: run the build edge realsense snapshot locked workflow with clear inputs and outputs.
    def _build_edge_realsense_snapshot_locked(self) -> Dict[str, Any]:
        is_available = self._is_edge_realsense_available_locked()
        age_ms = None
        if self.edge_realsense_updated_at:
            age_ms = int(max(0.0, (time.monotonic() - self.edge_realsense_updated_at) * 1000.0))

        # Prepare caps for the next step.
        caps = dict(self.edge_realsense_capabilities or {})
        caps['device_available'] = bool(is_available)
        caps['sdk_available'] = True
        if is_available:
            # Prepare values needed by the next step.
            caps['reason'] = None
        elif not caps.get('reason'):
            caps['reason'] = 'Edge relay frame is stale or unavailable'

        return {
            'edge_realsense_available': bool(is_available),
            'edge_realsense_device_name': self.edge_realsense_device_name,
            'edge_realsense_age_ms': age_ms,
            'edge_realsense_capabilities': caps,
        }

    # Section: run the get edge realsense snapshot workflow with clear inputs and outputs.
    def get_edge_realsense_snapshot(self) -> Dict[str, Any]:
        # Open the managed resource only for the block that needs it.
        with self.lock:
            # Return the prepared result to the caller.
            return self._build_edge_realsense_snapshot_locked()

    # Section: run the ingest edge realsense locked workflow with clear inputs and outputs.
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
        # Prepare edge realsense frame for the next step.
        self.edge_realsense_frame = frame
        self.edge_realsense_updated_at = time.monotonic()
        if device_name:
            # Prepare edge realsense device name for the next step.
            self.edge_realsense_device_name = str(device_name).strip() or self.edge_realsense_device_name

        if isinstance(depth_telemetry, dict):
            telemetry = self._default_depth_telemetry()
            telemetry.update(depth_telemetry)
            self.edge_realsense_depth_telemetry = telemetry
        else:
            self.edge_realsense_depth_telemetry = self._default_depth_telemetry()

        # Choose the correct branch before the workflow continues.
        if depth_preview_jpeg:
            # Prepare edge realsense depth preview jpeg for the next step.
            self.edge_realsense_depth_preview_jpeg = depth_preview_jpeg

        if isinstance(capabilities, dict):
            caps = dict(self.edge_realsense_capabilities)
            caps.update(capabilities)
            self.edge_realsense_capabilities = caps

        # Keep cache fresh: while edge relay is active, do not over-probe local webcams.
        # Prepare webcam probe cache ts for the next step.
        self._webcam_probe_cache_ts = time.monotonic()
        return self._build_edge_realsense_snapshot_locked()

    # Section: run the open webcam workflow with clear inputs and outputs.
    def _open_webcam(self, camera_index: int, probe_mode: bool = False):
        """Open webcam with backend fallbacks while keeping probe noise low on Windows."""
        cap = None
        preferred_backend = self._preferred_backend_by_index.get(int(camera_index))

        if os.name == 'nt':
            # Prepare allow probe msmf for the next step.
            allow_probe_msmf = os.getenv('WEBCAM_PROBE_USE_MSMF_WINDOWS', 'false').lower() in (
                '1', 'true', 'yes', 'on'
            )

            backend_candidates = []
            if hasattr(cv2, 'CAP_DSHOW'):
                # Trigger the side effect required for this stage.
                backend_candidates.append(cv2.CAP_DSHOW)
            if hasattr(cv2, 'CAP_MSMF') and (not probe_mode or allow_probe_msmf):
                backend_candidates.append(cv2.CAP_MSMF)

            # Choose the correct branch before the workflow continues.
            if preferred_backend:
                backend_candidates.sort(
                    key=lambda backend: 0 if self._backend_label(backend) == preferred_backend else 1
                )

            for backend in backend_candidates:
                # Prepare backend label for the next step.
                backend_label = self._backend_label(backend)
                if self._is_backend_suppressed(camera_index, backend_label):
                    continue

                try:
                    # Prepare cap for the next step.
                    cap = cv2.VideoCapture(camera_index, backend)
                except Exception:
                    cap = None

                # Choose the correct branch before the workflow continues.
                if cap is not None and cap.isOpened():
                    self._mark_backend_success(camera_index, backend_label)
                    return cap

                self._mark_backend_failure(camera_index, backend_label)

                try:
                    # Choose the correct branch before the workflow continues.
                    if cap is not None:
                        # Trigger the side effect required for this stage.
                        cap.release()
                except Exception:
                    pass
                # Prepare cap for the next step.
                cap = None

            # Prepare allow generic probe for the next step.
            allow_generic_probe = os.getenv('WEBCAM_PROBE_ALLOW_GENERIC_FALLBACK_WINDOWS', 'true').lower() in (
                '1', 'true', 'yes', 'on'
            )
            if probe_mode and not allow_generic_probe:
                try:
                    # Choose the correct branch before the workflow continues.
                    if cap is not None:
                        # Trigger the side effect required for this stage.
                        cap.release()
                except Exception:
                    pass
                # Return the prepared result to the caller.
                return None

        # Choose the correct branch before the workflow continues.
        if cap is None or not cap.isOpened():
            # Protect this step so expected failures can fall back cleanly.
            try:
                if cap is not None:
                    # Trigger the side effect required for this stage.
                    cap.release()
            except Exception:
                pass

            if self._is_backend_suppressed(camera_index, 'any'):
                # Return the prepared result to the caller.
                return None

            # Prepare cap for the next step.
            cap = cv2.VideoCapture(camera_index)

        # Choose the correct branch before the workflow continues.
        if cap is not None and cap.isOpened():
            self._mark_backend_success(camera_index, 'any')
        else:
            self._mark_backend_failure(camera_index, 'any')

        return cap

    # Section: run the list webcam devices workflow with clear inputs and outputs.
    def list_webcam_devices(self, max_index: int = 3, force_refresh: bool = False):
        """Probe likely webcam indexes and return openable device slots."""
        # Avoid probing every request; status endpoints can be polled frequently.
        # Prepare now for the next step.
        now = time.monotonic()
        cache_age = now - float(self._webcam_probe_cache_ts or 0.0)
        cache_window = (
            self.webcam_probe_cache_seconds
            if self._webcam_probe_cache
            else self.webcam_negative_probe_cache_seconds
        )
        cache_valid = self._webcam_probe_cache_ts > 0 and cache_age < cache_window
        if not force_refresh and cache_valid:
            # Return the prepared result to the caller.
            return list(self._webcam_probe_cache)

        # Prevent rapid forced refresh loops from hammering camera backends.
        # Choose the correct branch before the workflow continues.
        if force_refresh and self._webcam_probe_cache_ts > 0 and cache_age < 1.0:
            return list(self._webcam_probe_cache)

        # While webcam stream is active, probing other indexes can interfere with capture.
        if (
            self.active_camera_source == 'webcam'
            and self.active_camera is not None
            and self.active_camera.isOpened()
        ):
            # Prepare active only for the next step.
            active_only = [{'index': self.active_camera_index, 'label': f'Camera {self.active_camera_index}'}]
            self._webcam_probe_cache = list(active_only)
            self._webcam_probe_cache_ts = now
            return active_only

        # Prepare devices for the next step.
        devices = []
        configured_probe = os.getenv('WEBCAM_PROBE_MAX_INDEX')
        probe_seed = configured_probe if configured_probe not in (None, '') else max_index

        try:
            # Prepare max probe for the next step.
            max_probe = int(probe_seed)
        except Exception:
            max_probe = 3

        # Prepare max probe for the next step.
        max_probe = max(1, min(max_probe, 16))

        stop_on_gap = os.getenv('WEBCAM_PROBE_STOP_ON_GAP', 'true').lower() in ('1', 'true', 'yes', 'on')
        found_any = False

        for idx in range(max_probe):
            # Prepare cap for the next step.
            cap = None
            opened = False
            try:
                # Prepare cap for the next step.
                cap = self._open_webcam(idx, probe_mode=True)
                opened = cap is not None and cap.isOpened() and self._is_webcam_capture_ready(
                    cap,
                    attempts=max(1, min(2, self.webcam_start_warmup_attempts)),
                )
                if opened:
                    # Trigger the side effect required for this stage.
                    devices.append({'index': idx, 'label': f'Camera {idx}'})
                    found_any = True
            except Exception:
                continue
            finally:
                # Protect this step so expected failures can fall back cleanly.
                try:
                    if cap is not None:
                        # Trigger the side effect required for this stage.
                        cap.release()
                except Exception:
                    pass

            # Choose the correct branch before the workflow continues.
            if stop_on_gap and found_any and not opened:
                break

        # Prepare webcam probe cache for the next step.
        self._webcam_probe_cache = list(devices)
        self._webcam_probe_cache_ts = now
        return devices

    # Section: run the current source workflow with clear inputs and outputs.
    @property
    def current_source(self) -> str:
        return self.active_camera_source

    # Section: run the is active locked workflow with clear inputs and outputs.
    def is_active_locked(self) -> bool:
        """Return whether current source is active (lock must be held)."""
        # Choose the correct branch before the workflow continues.
        if self.active_camera_source == 'realsense':
            # Return the prepared result to the caller.
            return self.active_realsense_source is not None and self.active_realsense_source.pipeline is not None
        if self.active_camera_source == 'edge_realsense':
            return self._is_edge_realsense_available_locked()
        return self.active_camera is not None and self.active_camera.isOpened()

    # Section: run the stop locked workflow with clear inputs and outputs.
    def stop_locked(self) -> None:
        """Stop whichever source is active (lock must be held)."""
        if self.active_camera is not None:
            try:
                # Trigger the side effect required for this stage.
                self.active_camera.release()
            except Exception:
                pass
            # Prepare active camera for the next step.
            self.active_camera = None

        # Choose the correct branch before the workflow continues.
        if self.active_realsense_source is not None:
            try:
                self.active_realsense_source.stop()
            except Exception:
                pass

        self.active_camera_source = 'webcam'
        self._webcam_probe_cache_ts = 0.0

    # Section: run the get realsense probe source workflow with clear inputs and outputs.
    def _get_realsense_probe_source(self):
        # Choose the correct branch before the workflow continues.
        if not REALSENSE_SOURCE_AVAILABLE:
            # Return the prepared result to the caller.
            return None
        if self.active_realsense_source is not None:
            return self.active_realsense_source
        try:
            return RealSenseSource()
        except Exception:
            return None

    # Section: run the get realsense snapshot workflow with clear inputs and outputs.
    def get_realsense_snapshot(self) -> Dict[str, Any]:
        """Collect RealSense availability/capabilities in a uniform format."""
        # Prepare source for the next step.
        source = self._get_realsense_probe_source()
        if source is None:
            # Return the prepared result to the caller.
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

        # Prepare status for the next step.
        status = source.get_status()
        caps = source.get_capabilities()
        return {
            'realsense_available': bool(status.get('device_available')),
            'realsense_device_name': status.get('device_name'),
            'realsense_capabilities': caps
        }

    # Section: run the get default source workflow with clear inputs and outputs.
    def get_default_source(self) -> str:
        # Prepare snapshot for the next step.
        snapshot = self.get_realsense_snapshot()
        if snapshot['realsense_available']:
            # Return the prepared result to the caller.
            return 'realsense'

        edge_snapshot = self.get_edge_realsense_snapshot()
        if edge_snapshot.get('edge_realsense_available'):
            return 'edge_realsense'

        return 'webcam'

    # Section: run the start locked workflow with clear inputs and outputs.
    def start_locked(self, requested_source: str, camera_index: Optional[int] = None) -> Dict[str, Any]:
        """Start requested source with graceful fallback behavior (lock must be held)."""
        # Prepare source for the next step.
        source = (requested_source or 'webcam').strip().lower()
        if source not in ('webcam', 'realsense', 'edge_realsense'):
            # Prepare source for the next step.
            source = 'webcam'

        fallback_to_webcam = False
        fallback_message = None

        current_camera_index = self.active_camera_index

        # Protect this step so expected failures can fall back cleanly.
        try:
            desired_camera_index = int(self.active_camera_index if camera_index is None else camera_index)
        except Exception:
            # Prepare desired camera index for the next step.
            desired_camera_index = self.active_camera_index

        if desired_camera_index < 0:
            desired_camera_index = 0

        if self.is_active_locked() and self.active_camera_source == source:
            if source == 'webcam' and current_camera_index != desired_camera_index:
                pass
            else:
                # Return the prepared result to the caller.
                return {
                    'success': True,
                    'source': self.active_camera_source,
                    'camera_index': self.active_camera_index if self.active_camera_source == 'webcam' else None,
                    'fallback_to_webcam': False,
                    'message': f'Live monitoring already active on {self.active_camera_source}'
                }

        # Trigger the side effect required for this stage.
        self.stop_locked()

        if source == 'edge_realsense':
            # Choose the correct branch before the workflow continues.
            if self._is_edge_realsense_available_locked():
                # Prepare active camera source for the next step.
                self.active_camera_source = 'edge_realsense'
                return {
                    'success': True,
                    'source': 'edge_realsense',
                    'camera_index': None,
                    'fallback_to_webcam': False,
                    'message': 'Live monitoring started (Edge RealSense relay)'
                }

            # Choose the correct branch before the workflow continues.
            if not self._allow_realsense_webcam_fallback():
                # Return the prepared result to the caller.
                return {
                    'success': False,
                    'source': 'edge_realsense',
                    'camera_index': None,
                    'fallback_to_webcam': False,
                    'message': 'Edge RealSense relay is unavailable or stale. Start the edge relay and wait for fresh frames before selecting it.'
                }

            # Prepare source for the next step.
            source = 'webcam'
            fallback_to_webcam = True
            fallback_message = 'Edge RealSense relay is unavailable or stale; switched to webcam.'

        # Choose the correct branch before the workflow continues.
        if source == 'realsense':
            if not REALSENSE_SOURCE_AVAILABLE:
                # Choose the correct branch before the workflow continues.
                if not self._allow_realsense_webcam_fallback():
                    # Return the prepared result to the caller.
                    return {
                        'success': False,
                        'source': 'realsense',
                        'camera_index': None,
                        'fallback_to_webcam': False,
                        'message': 'RealSense SDK is unavailable. Install pyrealsense2 on the local workstation before selecting RealSense USB.'
                    }
                source = 'webcam'
                # Prepare fallback to webcam for the next step.
                fallback_to_webcam = True
                fallback_message = 'RealSense SDK is unavailable; switched to webcam.'
            else:
                try:
                    # Prepare active realsense source for the next step.
                    self.active_realsense_source = RealSenseSource()
                    started, error_message = self.active_realsense_source.start()
                except Exception as exc:
                    started = False
                    error_message = str(exc)

                # Choose the correct branch before the workflow continues.
                if started:
                    self.active_camera_source = 'realsense'
                    return {
                        'success': True,
                        'source': 'realsense',
                        'camera_index': None,
                        'fallback_to_webcam': False,
                        'message': 'Live monitoring started (RealSense)'
                    }

                # Protect this step so expected failures can fall back cleanly.
                try:
                    # Choose the correct branch before the workflow continues.
                    if self.active_realsense_source is not None:
                        # Trigger the side effect required for this stage.
                        self.active_realsense_source.stop()
                except Exception:
                    pass
                self.active_realsense_source = None

                if not self._allow_realsense_webcam_fallback():
                    return {
                        'success': False,
                        'source': 'realsense',
                        'camera_index': None,
                        'fallback_to_webcam': False,
                        'message': f'RealSense unavailable ({error_message}). Webcam fallback is disabled for explicit RealSense selections.'
                    }

                # Prepare source for the next step.
                source = 'webcam'
                fallback_to_webcam = True
                fallback_message = f'RealSense unavailable ({error_message}); switched to webcam.'

        # Prepare active camera for the next step.
        self.active_camera = self._open_webcam(desired_camera_index)
        opened_index = desired_camera_index
        if self.active_camera is not None and self.active_camera.isOpened():
            # Choose the correct branch before the workflow continues.
            if not self._is_webcam_capture_ready(self.active_camera):
                try:
                    # Trigger the side effect required for this stage.
                    self.active_camera.release()
                except Exception:
                    pass
                # Prepare active camera for the next step.
                self.active_camera = None

        # Choose the correct branch before the workflow continues.
        if self.active_camera is None or not self.active_camera.isOpened():
            try:
                if self.active_camera is not None:
                    self.active_camera.release()
            except Exception:
                pass
            # Prepare active camera for the next step.
            self.active_camera = None

            # Try any other available index to avoid hard failure on systems where index 0 is not a webcam.
            for device in self.list_webcam_devices(force_refresh=True):
                idx = int(device.get('index', -1))
                if idx < 0 or idx == desired_camera_index:
                    continue

                candidate = self._open_webcam(idx)
                if candidate is not None and candidate.isOpened() and self._is_webcam_capture_ready(candidate):
                    # Prepare active camera for the next step.
                    self.active_camera = candidate
                    opened_index = idx
                    break

                # Protect this step so expected failures can fall back cleanly.
                try:
                    if candidate is not None:
                        # Trigger the side effect required for this stage.
                        candidate.release()
                except Exception:
                    pass

        # Choose the correct branch before the workflow continues.
        if self.active_camera is None or not self.active_camera.isOpened():
            # Prepare active camera for the next step.
            self.active_camera = None
            self.active_camera_index = desired_camera_index
            available_indexes = [str(d.get('index')) for d in self.list_webcam_devices(force_refresh=True)]
            available_label = ', '.join(available_indexes) if available_indexes else 'none'
            return {
                'success': False,
                'source': 'webcam',
                'camera_index': desired_camera_index,
                'fallback_to_webcam': False,
                'message': (
                    f'Failed to open webcam or read frames '
                    f'(requested index {desired_camera_index}; available indexes: {available_label})'
                )
            }

        # Keep webcam buffer small to avoid stale-frame lag in annotated stream.
        # Protect this step so expected failures can fall back cleanly.
        try:
            self.active_camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.active_camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.active_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.active_camera.set(cv2.CAP_PROP_FPS, 30)
        except Exception:
            pass

        self.active_camera_source = 'webcam'
        # Prepare active camera index for the next step.
        self.active_camera_index = opened_index
        self._persist_last_good_camera_index(self.active_camera_index)
        if fallback_to_webcam and fallback_message:
            # Prepare start message for the next step.
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

    # Section: run the read frame locked workflow with clear inputs and outputs.
    def read_frame_locked(self) -> Tuple[bool, Optional[Any], Optional[str]]:
        """Read one frame from current source (lock must be held)."""
        # Choose the correct branch before the workflow continues.
        if self.active_camera_source == 'realsense':
            # Choose the correct branch before the workflow continues.
            if self.active_realsense_source is None:
                # Return the prepared result to the caller.
                return False, None, 'RealSense source is not initialized'
            return self.active_realsense_source.read()

        if self.active_camera_source == 'edge_realsense':
            if not self._is_edge_realsense_available_locked() or self.edge_realsense_frame is None:
                return False, None, 'Edge RealSense relay frame is unavailable or stale'
            try:
                return True, self.edge_realsense_frame.copy(), None
            except Exception:
                # Return the prepared result to the caller.
                return True, self.edge_realsense_frame, None

        # Choose the correct branch before the workflow continues.
        if self.active_camera is None or not self.active_camera.isOpened():
            # Return the prepared result to the caller.
            return False, None, 'Webcam is not opened'

        ok, frame = self._read_webcam_frame_with_retries(self.active_camera, delay_seconds=0.02)
        if ok:
            return True, frame, None

        # A single self-heal attempt handles transient Windows capture stalls.
        try:
            self.active_camera.release()
        except Exception:
            pass

        # Prepare reopened for the next step.
        reopened = self._open_webcam(self.active_camera_index)
        if reopened is not None and reopened.isOpened():
            # Prepare active camera for the next step.
            self.active_camera = reopened
            ok, frame = self._read_webcam_frame_with_retries(
                self.active_camera,
                attempts=max(2, min(self.webcam_read_retry_attempts, 6)),
                delay_seconds=self.webcam_start_warmup_sleep_seconds,
            )
            if ok:
                # Return the prepared result to the caller.
                return True, frame, None
        else:
            # Prepare active camera for the next step.
            self.active_camera = reopened

        # Return the prepared result to the caller.
        return False, None, 'Failed to read webcam frame'

    # Section: run the get depth telemetry locked workflow with clear inputs and outputs.
    def get_depth_telemetry_locked(self) -> Dict[str, Any]:
        """Get depth telemetry for active RealSense source (lock must be held)."""
        if self.active_camera_source == 'realsense' and self.active_realsense_source is not None:
            return self.active_realsense_source.get_depth_telemetry()

        if self.active_camera_source == 'edge_realsense':
            # Return the prepared result to the caller.
            return dict(self.edge_realsense_depth_telemetry)

        # Return the prepared result to the caller.
        return self._default_depth_telemetry()

    # Section: run the get depth preview locked workflow with clear inputs and outputs.
    def get_depth_preview_locked(self):
        """Get latest depth preview jpeg for active RealSense source (lock must be held)."""
        if self.active_camera_source == 'realsense' and self.active_realsense_source is not None:
            return self.active_realsense_source.get_depth_preview_jpeg()

        if self.active_camera_source == 'edge_realsense':
            # Return the prepared result to the caller.
            return self.edge_realsense_depth_preview_jpeg

        # Return the prepared result to the caller.
        return None

    # Section: run the build state payload workflow with clear inputs and outputs.
    def build_state_payload(self, force_webcam_refresh: bool = False) -> Dict[str, Any]:
        """Build live state payload consumed by frontend controls."""
        with self.lock:
            is_active = self.is_active_locked()
            source = self.active_camera_source
            # Prepare active camera index for the next step.
            active_camera_index = self.active_camera_index
            edge_snapshot = self._build_edge_realsense_snapshot_locked()

        # Prepare rs snapshot for the next step.
        rs_snapshot = self.get_realsense_snapshot()
        if rs_snapshot['realsense_available']:
            default_source = 'realsense'
        elif edge_snapshot.get('edge_realsense_available'):
            default_source = 'edge_realsense'
        else:
            # Prepare default source for the next step.
            default_source = 'webcam'
        webcam_devices = self.list_webcam_devices(force_refresh=bool(force_webcam_refresh and not is_active))
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
