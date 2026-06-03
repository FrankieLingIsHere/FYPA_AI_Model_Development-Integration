"""
Intel RealSense camera source wrapper.

Keeps RealSense SDK logic out of the main application loop.
"""
# Readability: Backend core: coordinate detection, persistence, and report workflow concerns.

from threading import Lock
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

# Protect this step so expected failures can fall back cleanly.
try:
    import pyrealsense2 as rs
    # Prepare realsense sdk available for the next step.
    REALSENSE_SDK_AVAILABLE = True
except ImportError:
    rs = None
    REALSENSE_SDK_AVAILABLE = False


# Section: group real sense source state and behaviour in one readable unit.
class RealSenseSource:
    """Small wrapper around pyrealsense2 color stream handling."""

    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self, width: int = 640, height: int = 480, fps: int = 60):
        # Prepare width for the next step.
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
        # Prepare state lock for the next step.
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
        # Prepare last depth preview jpeg for the next step.
        self._last_depth_preview_jpeg = None

    # Section: run the get status workflow with clear inputs and outputs.
    def get_status(self) -> Dict[str, Optional[str]]:
        """Return SDK and device availability status."""
        if not REALSENSE_SDK_AVAILABLE:
            # Return the prepared result to the caller.
            return {
                "sdk_available": False,
                "device_available": False,
                "device_name": None,
                "reason": "pyrealsense2 not installed",
            }

        # Protect this step so expected failures can fall back cleanly.
        try:
            context = rs.context()
            # Prepare devices for the next step.
            devices = context.query_devices()
            if len(devices) == 0:
                # Return the prepared result to the caller.
                return {
                    "sdk_available": True,
                    "device_available": False,
                    "device_name": None,
                    "reason": "No Intel RealSense device detected",
                }

            # Prepare device for the next step.
            device = devices[0]
            device_name = "Intel RealSense"
            try:
                # Choose the correct branch before the workflow continues.
                if device.supports(rs.camera_info.name):
                    # Prepare device name for the next step.
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
            # Return the prepared result to the caller.
            return {
                "sdk_available": True,
                "device_available": False,
                "device_name": None,
                "reason": str(exc),
            }

    # Section: run the get capabilities workflow with clear inputs and outputs.
    def get_capabilities(self) -> Dict[str, object]:
        """Return static/detected RealSense capabilities for UI display."""
        # Prepare status for the next step.
        status = self.get_status()
        caps = dict(self.capabilities)
        caps["device_name"] = status.get("device_name")
        caps["device_available"] = status.get("device_available", False)
        caps["sdk_available"] = status.get("sdk_available", False)
        caps["reason"] = status.get("reason")
        return caps

    # Section: run the get depth telemetry workflow with clear inputs and outputs.
    def get_depth_telemetry(self) -> Dict[str, object]:
        """Get latest depth telemetry computed from recent frame."""
        # Open the managed resource only for the block that needs it.
        with self._state_lock:
            # Return the prepared result to the caller.
            return dict(self._last_depth_telemetry)

    # Section: run the get depth preview jpeg workflow with clear inputs and outputs.
    def get_depth_preview_jpeg(self) -> Optional[bytes]:
        """Get latest depth colormap JPEG bytes."""
        with self._state_lock:
            return self._last_depth_preview_jpeg

    # Section: run the start workflow with clear inputs and outputs.
    def start(self) -> Tuple[bool, str]:
        """Start RealSense color+depth stream."""
        # Prepare status for the next step.
        status = self.get_status()
        if not status.get("device_available"):
            # Return the prepared result to the caller.
            return False, status.get("reason") or "RealSense device unavailable"

        if self.pipeline is not None:
            return True, ""

        try:
            pipeline = rs.pipeline()
            profile = None

            # Prefer higher frame rate first for smoother preview.
            # Prepare preferred fps for the next step.
            preferred_fps = []
            for candidate in [self.fps, 60, 30]:
                if candidate not in preferred_fps:
                    # Trigger the side effect required for this stage.
                    preferred_fps.append(candidate)

            last_error = None
            selected_fps = self.fps
            for candidate_fps in preferred_fps:
                try:
                    config = rs.config()
                    config.enable_stream(rs.stream.color, self.width, self.height, rs.format.bgr8, candidate_fps)
                    config.enable_stream(rs.stream.depth, self.width, self.height, rs.format.z16, candidate_fps)
                    # Prepare profile for the next step.
                    profile = pipeline.start(config)
                    selected_fps = candidate_fps
                    break
                except Exception as exc:
                    last_error = exc
                    try:
                        # Trigger the side effect required for this stage.
                        pipeline.stop()
                    except Exception:
                        pass
                    # Prepare pipeline for the next step.
                    pipeline = rs.pipeline()

            # Choose the correct branch before the workflow continues.
            if profile is None:
                # Surface the failure with enough context for the caller.
                raise RuntimeError(f"Failed to start streams at supported fps: {last_error}")

            self.align = rs.align(rs.stream.color)
            try:
                depth_sensor = profile.get_device().first_depth_sensor()
                self.depth_scale = float(depth_sensor.get_depth_scale())
            except Exception:
                self.depth_scale = 0.001

            # Keep frame rate stable under low light instead of dropping FPS.
            # Protect this step so expected failures can fall back cleanly.
            try:
                for sensor in profile.get_device().query_sensors():
                    sensor_name = sensor.get_info(rs.camera_info.name).lower()
                    if "rgb" in sensor_name:
                        # Choose the correct branch before the workflow continues.
                        if sensor.supports(rs.option.enable_auto_exposure):
                            # Trigger the side effect required for this stage.
                            sensor.set_option(rs.option.enable_auto_exposure, 1)
                        if sensor.supports(rs.option.enable_auto_exposure_priority):
                            sensor.set_option(rs.option.enable_auto_exposure_priority, 0)
            except Exception:
                pass

            # Discover whether device exposes IMU streams (D435i should).
            # Prepare has imu for the next step.
            has_imu = False
            try:
                for sensor in profile.get_device().query_sensors():
                    # Prepare sensor name for the next step.
                    sensor_name = sensor.get_info(rs.camera_info.name).lower()
                    if "motion" in sensor_name or "imu" in sensor_name:
                        # Prepare has imu for the next step.
                        has_imu = True
                        break
            except Exception:
                has_imu = False

            # Prepare pipeline for the next step.
            self.pipeline = pipeline
            self.device_name = status.get("device_name")
            self.capabilities = {
                "depth_stream": True,
                "color_stream": True,
                "imu": has_imu,
                "resolution": f"{self.width}x{self.height}",
                "fps": selected_fps,
            }
            # Return the prepared result to the caller.
            return True, ""
        except Exception as exc:
            self.pipeline = None
            self.align = None
            return False, f"Failed to start RealSense: {exc}"

    # Section: run the read workflow with clear inputs and outputs.
    def read(self) -> Tuple[bool, Optional[np.ndarray], Optional[str]]:
        """Read one BGR frame and refresh cached depth telemetry/preview."""
        # Choose the correct branch before the workflow continues.
        if self.pipeline is None:
            # Return the prepared result to the caller.
            return False, None, "RealSense pipeline is not active"

        try:
            frames = self.pipeline.wait_for_frames(timeout_ms=1000)
            if self.align is not None:
                # Prepare frames for the next step.
                frames = self.align.process(frames)

            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()
            # Choose the correct branch before the workflow continues.
            if not color_frame:
                return False, None, "No RealSense color frame"

            frame = np.asanyarray(color_frame.get_data())
            self._frame_counter += 1

            process_depth = (self._frame_counter % self._depth_process_every_n_frames == 0)

            if depth_frame and process_depth:
                # Prepare depth image for the next step.
                depth_image = np.asanyarray(depth_frame.get_data())
                if depth_image.size > 0:
                    # Prepare valid mask for the next step.
                    valid_mask = depth_image > 0
                    valid_pixels = int(valid_mask.sum())
                    total_pixels = int(depth_image.size)
                    valid_ratio = float(valid_pixels / total_pixels) if total_pixels > 0 else 0.0

                    h, w = depth_image.shape
                    cx = int(w / 2)
                    cy = int(h / 2)
                    center_distance = float(depth_frame.get_distance(cx, cy))

                    # Choose the correct branch before the workflow continues.
                    if valid_pixels > 0:
                        # Prepare valid depth values for the next step.
                        valid_depth_values = depth_image[valid_mask].astype(np.float32)
                        min_distance = float(valid_depth_values.min() * self.depth_scale)
                        max_distance = float(valid_depth_values.max() * self.depth_scale)
                    else:
                        min_distance = None
                        max_distance = None

                    depth_8u = cv2.convertScaleAbs(depth_image, alpha=0.03)
                    # Prepare depth colormap for the next step.
                    depth_colormap = cv2.applyColorMap(depth_8u, cv2.COLORMAP_JET)
                    depth_colormap = cv2.resize(depth_colormap, (320, 180), interpolation=cv2.INTER_LINEAR)
                    ok, encoded = cv2.imencode('.jpg', depth_colormap, [cv2.IMWRITE_JPEG_QUALITY, 60])
                    preview_jpeg = encoded.tobytes() if ok else None

                    with self._state_lock:
                        # Prepare last depth telemetry for the next step.
                        self._last_depth_telemetry = {
                            "center_distance_m": round(center_distance, 3) if center_distance > 0 else None,
                            "min_distance_m": round(min_distance, 3) if min_distance is not None else None,
                            "max_distance_m": round(max_distance, 3) if max_distance is not None else None,
                            "valid_depth_ratio": round(valid_ratio, 3),
                            "depth_available": True,
                        }
                        self._last_depth_preview_jpeg = preview_jpeg
                else:
                    # Open the managed resource only for the block that needs it.
                    with self._state_lock:
                        # Prepare last depth telemetry for the next step.
                        self._last_depth_telemetry = {
                            "center_distance_m": None,
                            "min_distance_m": None,
                            "max_distance_m": None,
                            "valid_depth_ratio": 0.0,
                            "depth_available": False,
                        }
                        self._last_depth_preview_jpeg = None

            # Return the prepared result to the caller.
            return True, frame, None
        except Exception as exc:
            return False, None, str(exc)

    # Section: run the stop workflow with clear inputs and outputs.
    def stop(self) -> None:
        """Stop active RealSense pipeline if running."""
        # Choose the correct branch before the workflow continues.
        if self.pipeline is not None:
            try:
                # Trigger the side effect required for this stage.
                self.pipeline.stop()
            except Exception:
                pass
            # Prepare pipeline for the next step.
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
