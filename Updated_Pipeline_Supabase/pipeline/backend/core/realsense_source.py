"""
Intel RealSense camera source wrapper.

Keeps RealSense SDK logic out of the main application loop.
"""

from threading import Lock
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

try:
    import pyrealsense2 as rs
    REALSENSE_SDK_AVAILABLE = True
except ImportError:
    rs = None
    REALSENSE_SDK_AVAILABLE = False


class RealSenseSource:
    """Small wrapper around pyrealsense2 color stream handling."""

    def __init__(self, width: int = 640, height: int = 480, fps: int = 60):
        self.width = width
        self.height = height
        self.fps = fps
        self.pipeline = None
        self.align = None
        self.depth_scale = 0.001
        self.device_name = None
        self.capabilities = {
            "depth_stream": False,
            "color_stream": False,
            "imu": False,
            "resolution": f"{self.width}x{self.height}",
            "fps": self.fps,
        }
        self._state_lock = Lock()
        self._frame_counter = 0
        self._depth_process_every_n_frames = 4
        self._last_depth_telemetry = {
            "center_distance_m": None,
            "min_distance_m": None,
            "max_distance_m": None,
            "valid_depth_ratio": 0.0,
            "depth_available": False,
        }
        self._last_depth_preview_jpeg = None

    def get_status(self) -> Dict[str, Optional[str]]:
        """Return SDK and device availability status."""
        if not REALSENSE_SDK_AVAILABLE:
            return {
                "sdk_available": False,
                "device_available": False,
                "device_name": None,
                "reason": "pyrealsense2 not installed",
            }

        try:
            context = rs.context()
            devices = context.query_devices()
            if len(devices) == 0:
                return {
                    "sdk_available": True,
                    "device_available": False,
                    "device_name": None,
                    "reason": "No Intel RealSense device detected",
                }

            device = devices[0]
            device_name = "Intel RealSense"
            try:
                if device.supports(rs.camera_info.name):
                    device_name = device.get_info(rs.camera_info.name)
            except Exception:
                pass

            return {
                "sdk_available": True,
                "device_available": True,
                "device_name": device_name,
                "reason": None,
            }
        except Exception as exc:
            return {
                "sdk_available": True,
                "device_available": False,
                "device_name": None,
                "reason": str(exc),
            }

    def get_capabilities(self) -> Dict[str, object]:
        """Return static/detected RealSense capabilities for UI display."""
        status = self.get_status()
        caps = dict(self.capabilities)
        caps["device_name"] = status.get("device_name")
        caps["device_available"] = status.get("device_available", False)
        caps["sdk_available"] = status.get("sdk_available", False)
        caps["reason"] = status.get("reason")
        return caps

    def get_depth_telemetry(self) -> Dict[str, object]:
        """Get latest depth telemetry computed from recent frame."""
        with self._state_lock:
            return dict(self._last_depth_telemetry)

    def get_depth_preview_jpeg(self) -> Optional[bytes]:
        """Get latest depth colormap JPEG bytes."""
        with self._state_lock:
            return self._last_depth_preview_jpeg

    def start(self) -> Tuple[bool, str]:
        """Start RealSense color+depth stream."""
        status = self.get_status()
        if not status.get("device_available"):
            return False, status.get("reason") or "RealSense device unavailable"

        if self.pipeline is not None:
            return True, ""

        try:
            pipeline = rs.pipeline()
            profile = None

            # Prefer higher frame rate first for smoother preview.
            preferred_fps = []
            for candidate in [self.fps, 60, 30]:
                if candidate not in preferred_fps:
                    preferred_fps.append(candidate)

            last_error = None
            selected_fps = self.fps
            for candidate_fps in preferred_fps:
                try:
                    config = rs.config()
                    config.enable_stream(rs.stream.color, self.width, self.height, rs.format.bgr8, candidate_fps)
                    config.enable_stream(rs.stream.depth, self.width, self.height, rs.format.z16, candidate_fps)
                    profile = pipeline.start(config)
                    selected_fps = candidate_fps
                    break
                except Exception as exc:
                    last_error = exc
                    try:
                        pipeline.stop()
                    except Exception:
                        pass
                    pipeline = rs.pipeline()

            if profile is None:
                raise RuntimeError(f"Failed to start streams at supported fps: {last_error}")

            self.align = rs.align(rs.stream.color)
            try:
                depth_sensor = profile.get_device().first_depth_sensor()
                self.depth_scale = float(depth_sensor.get_depth_scale())
            except Exception:
                self.depth_scale = 0.001

            # Keep frame rate stable under low light instead of dropping FPS.
            try:
                for sensor in profile.get_device().query_sensors():
                    sensor_name = sensor.get_info(rs.camera_info.name).lower()
                    if "rgb" in sensor_name:
                        if sensor.supports(rs.option.enable_auto_exposure):
                            sensor.set_option(rs.option.enable_auto_exposure, 1)
                        if sensor.supports(rs.option.enable_auto_exposure_priority):
                            sensor.set_option(rs.option.enable_auto_exposure_priority, 0)
            except Exception:
                pass

            # Discover whether device exposes IMU streams (D435i should).
            has_imu = False
            try:
                for sensor in profile.get_device().query_sensors():
                    sensor_name = sensor.get_info(rs.camera_info.name).lower()
                    if "motion" in sensor_name or "imu" in sensor_name:
                        has_imu = True
                        break
            except Exception:
                has_imu = False

            self.pipeline = pipeline
            self.device_name = status.get("device_name")
            self.capabilities = {
                "depth_stream": True,
                "color_stream": True,
                "imu": has_imu,
                "resolution": f"{self.width}x{self.height}",
                "fps": selected_fps,
            }
            return True, ""
        except Exception as exc:
            self.pipeline = None
            self.align = None
            return False, f"Failed to start RealSense: {exc}"

    def read(self) -> Tuple[bool, Optional[np.ndarray], Optional[str]]:
        """Read one BGR frame and refresh cached depth telemetry/preview."""
        if self.pipeline is None:
            return False, None, "RealSense pipeline is not active"

        try:
            frames = self.pipeline.wait_for_frames(timeout_ms=1000)
            if self.align is not None:
                frames = self.align.process(frames)

            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()
            if not color_frame:
                return False, None, "No RealSense color frame"

            frame = np.asanyarray(color_frame.get_data())
            self._frame_counter += 1

            process_depth = (self._frame_counter % self._depth_process_every_n_frames == 0)

            if depth_frame and process_depth:
                depth_image = np.asanyarray(depth_frame.get_data())
                if depth_image.size > 0:
                    valid_mask = depth_image > 0
                    valid_pixels = int(valid_mask.sum())
                    total_pixels = int(depth_image.size)
                    valid_ratio = float(valid_pixels / total_pixels) if total_pixels > 0 else 0.0

                    h, w = depth_image.shape
                    cx = int(w / 2)
                    cy = int(h / 2)
                    center_distance = float(depth_frame.get_distance(cx, cy))

                    if valid_pixels > 0:
                        valid_depth_values = depth_image[valid_mask].astype(np.float32)
                        min_distance = float(valid_depth_values.min() * self.depth_scale)
                        max_distance = float(valid_depth_values.max() * self.depth_scale)
                    else:
                        min_distance = None
                        max_distance = None

                    depth_8u = cv2.convertScaleAbs(depth_image, alpha=0.03)
                    depth_colormap = cv2.applyColorMap(depth_8u, cv2.COLORMAP_JET)
                    depth_colormap = cv2.resize(depth_colormap, (320, 180), interpolation=cv2.INTER_LINEAR)
                    ok, encoded = cv2.imencode('.jpg', depth_colormap, [cv2.IMWRITE_JPEG_QUALITY, 60])
                    preview_jpeg = encoded.tobytes() if ok else None

                    with self._state_lock:
                        self._last_depth_telemetry = {
                            "center_distance_m": round(center_distance, 3) if center_distance > 0 else None,
                            "min_distance_m": round(min_distance, 3) if min_distance is not None else None,
                            "max_distance_m": round(max_distance, 3) if max_distance is not None else None,
                            "valid_depth_ratio": round(valid_ratio, 3),
                            "depth_available": True,
                        }
                        self._last_depth_preview_jpeg = preview_jpeg
                else:
                    with self._state_lock:
                        self._last_depth_telemetry = {
                            "center_distance_m": None,
                            "min_distance_m": None,
                            "max_distance_m": None,
                            "valid_depth_ratio": 0.0,
                            "depth_available": False,
                        }
                        self._last_depth_preview_jpeg = None

            return True, frame, None
        except Exception as exc:
            return False, None, str(exc)

    def stop(self) -> None:
        """Stop active RealSense pipeline if running."""
        if self.pipeline is not None:
            try:
                self.pipeline.stop()
            except Exception:
                pass
            self.pipeline = None
        self.align = None
        with self._state_lock:
            self._last_depth_preview_jpeg = None
            self._last_depth_telemetry = {
                "center_distance_m": None,
                "min_distance_m": None,
                "max_distance_m": None,
                "valid_depth_ratio": 0.0,
                "depth_available": False,
            }
