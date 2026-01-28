"""
Intel RealSense D435i Camera Module
===================================
Provides unified camera interface with RealSense as primary and webcam fallback.
Supports RGB stream for PPE detection and depth visualization.
"""

import cv2
import numpy as np
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Try to import RealSense SDK
REALSENSE_AVAILABLE = False
try:
    import pyrealsense2 as rs
    REALSENSE_AVAILABLE = True
    logger.info("RealSense SDK loaded successfully")
except ImportError:
    logger.warning("pyrealsense2 not installed - RealSense cameras will not be available")


class RealSenseCamera:
    """
    Intel RealSense D435i camera wrapper with depth visualization.
    Falls back to standard webcam if RealSense is not available.
    """
    
    def __init__(self, width=640, height=480, fps=30, enable_depth=True):
        """
        Initialize the camera.
        
        Args:
            width: Frame width (default 640)
            height: Frame height (default 480)
            fps: Frames per second (default 30)
            enable_depth: Whether to enable depth stream (default True)
        """
        self.width = width
        self.height = height
        self.fps = fps
        self.enable_depth = enable_depth
        
        self.pipeline = None
        self.config = None
        self.align = None
        self.colorizer = None
        
        self.webcam = None
        self.using_realsense = False
        self.is_opened = False
        
        # Depth colormap settings
        self.depth_min = 0.1  # meters
        self.depth_max = 4.0  # meters
        
    def open(self):
        """
        Open the camera. Tries RealSense first, falls back to webcam.
        
        Returns:
            bool: True if camera opened successfully
        """
        if self.is_opened:
            return True
            
        # Try RealSense first
        if REALSENSE_AVAILABLE:
            try:
                self.pipeline = rs.pipeline()
                self.config = rs.config()
                
                # Check if RealSense device is connected
                ctx = rs.context()
                devices = ctx.query_devices()
                
                if len(devices) > 0:
                    device_name = devices[0].get_info(rs.camera_info.name)
                    logger.info(f"Found RealSense device: {device_name}")
                    
                    # Configure streams
                    self.config.enable_stream(
                        rs.stream.color, 
                        self.width, self.height, 
                        rs.format.bgr8, 
                        self.fps
                    )
                    
                    if self.enable_depth:
                        self.config.enable_stream(
                            rs.stream.depth, 
                            self.width, self.height, 
                            rs.format.z16, 
                            self.fps
                        )
                    
                    # Start pipeline
                    profile = self.pipeline.start(self.config)
                    
                    # Get device for configuration
                    device = profile.get_device()
                    
                    # Try to enable auto-exposure for better image quality
                    try:
                        color_sensor = device.first_color_sensor()
                        color_sensor.set_option(rs.option.enable_auto_exposure, 1)
                    except Exception as e:
                        logger.warning(f"Could not set auto-exposure: {e}")
                    
                    # Setup alignment (align depth to color)
                    if self.enable_depth:
                        self.align = rs.align(rs.stream.color)
                        self.colorizer = rs.colorizer()
                        # Set colorizer options for better visualization
                        self.colorizer.set_option(rs.option.color_scheme, 2)  # White to Black
                    
                    self.using_realsense = True
                    self.is_opened = True
                    logger.info(f"RealSense camera opened: {self.width}x{self.height} @ {self.fps}fps")
                    return True
                    
            except Exception as e:
                logger.warning(f"Failed to initialize RealSense: {e}")
                if self.pipeline:
                    try:
                        self.pipeline.stop()
                    except:
                        pass
                self.pipeline = None
        
        # Fallback to webcam
        logger.info("Falling back to standard webcam...")
        self.webcam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        
        if self.webcam.isOpened():
            self.webcam.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.webcam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.webcam.set(cv2.CAP_PROP_FPS, self.fps)
            
            self.using_realsense = False
            self.is_opened = True
            logger.info(f"Webcam opened: {self.width}x{self.height} @ {self.fps}fps")
            return True
        
        logger.error("Failed to open any camera!")
        return False
    
    def read(self):
        """
        Read a frame from the camera.
        
        Returns:
            tuple: (success, color_frame, depth_frame, depth_colormap)
                - success: bool indicating if frame was read
                - color_frame: BGR color image (numpy array)
                - depth_frame: Raw depth data (numpy array) or None
                - depth_colormap: Colorized depth image (numpy array) or None
        """
        if not self.is_opened:
            return False, None, None, None
            
        if self.using_realsense:
            return self._read_realsense()
        else:
            return self._read_webcam()
    
    def _read_realsense(self):
        """Read frame from RealSense camera."""
        try:
            # Wait for frames with timeout
            frames = self.pipeline.wait_for_frames(timeout_ms=5000)
            
            if self.enable_depth and self.align:
                # Align depth to color
                aligned_frames = self.align.process(frames)
                color_frame = aligned_frames.get_color_frame()
                depth_frame = aligned_frames.get_depth_frame()
            else:
                color_frame = frames.get_color_frame()
                depth_frame = None
            
            if not color_frame:
                return False, None, None, None
            
            # Convert to numpy arrays
            color_image = np.asanyarray(color_frame.get_data())
            
            depth_image = None
            depth_colormap = None
            
            if depth_frame and self.enable_depth:
                depth_image = np.asanyarray(depth_frame.get_data())
                
                # Create colorized depth map
                depth_colormap = np.asanyarray(
                    self.colorizer.colorize(depth_frame).get_data()
                )
            
            return True, color_image, depth_image, depth_colormap
            
        except Exception as e:
            logger.warning(f"RealSense read error: {e}")
            return False, None, None, None
    
    def _read_webcam(self):
        """Read frame from standard webcam."""
        ret, frame = self.webcam.read()
        if ret:
            # Create a dummy depth visualization (gray placeholder)
            if self.enable_depth:
                depth_placeholder = np.zeros(
                    (self.height, self.width, 3), 
                    dtype=np.uint8
                )
                cv2.putText(
                    depth_placeholder, 
                    "Depth N/A (Webcam)", 
                    (self.width // 4, self.height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 
                    0.7, 
                    (128, 128, 128), 
                    2
                )
                return True, frame, None, depth_placeholder
            return True, frame, None, None
        return False, None, None, None
    
    def release(self):
        """Release camera resources."""
        if self.using_realsense and self.pipeline:
            try:
                self.pipeline.stop()
                logger.info("RealSense pipeline stopped")
            except Exception as e:
                logger.warning(f"Error stopping RealSense: {e}")
        
        if self.webcam:
            self.webcam.release()
            logger.info("Webcam released")
        
        self.is_opened = False
        self.pipeline = None
        self.webcam = None
    
    def isOpened(self):
        """Check if camera is opened."""
        return self.is_opened
    
    def get_camera_info(self):
        """Get information about the current camera."""
        if self.using_realsense:
            try:
                ctx = rs.context()
                devices = ctx.query_devices()
                if len(devices) > 0:
                    device = devices[0]
                    return {
                        'type': 'RealSense',
                        'name': device.get_info(rs.camera_info.name),
                        'serial': device.get_info(rs.camera_info.serial_number),
                        'firmware': device.get_info(rs.camera_info.firmware_version),
                        'depth_enabled': self.enable_depth,
                        'resolution': f"{self.width}x{self.height}",
                        'fps': self.fps
                    }
            except:
                pass
        
        return {
            'type': 'Webcam',
            'name': 'Standard Webcam (DirectShow)',
            'depth_enabled': False,
            'resolution': f"{self.width}x{self.height}",
            'fps': self.fps
        }


def create_combined_view(color_frame, depth_colormap, detection_frame=None):
    """
    Create a combined view showing RGB and depth side by side.
    
    Args:
        color_frame: Original color frame
        depth_colormap: Colorized depth map
        detection_frame: Frame with detection overlays (optional, uses color_frame if None)
    
    Returns:
        numpy array: Combined image with RGB (with detections) and depth side by side
    """
    if detection_frame is None:
        detection_frame = color_frame.copy()
    
    if depth_colormap is None:
        # If no depth, just return the detection frame
        return detection_frame
    
    # Ensure same height
    h1, w1 = detection_frame.shape[:2]
    h2, w2 = depth_colormap.shape[:2]
    
    if h1 != h2:
        # Resize depth to match color height
        depth_colormap = cv2.resize(depth_colormap, (w2, h1))
    
    # Add labels
    labeled_color = detection_frame.copy()
    labeled_depth = depth_colormap.copy()
    
    # Add "RGB + Detection" label
    cv2.rectangle(labeled_color, (5, 5), (180, 35), (0, 0, 0), -1)
    cv2.putText(
        labeled_color, "RGB + Detection", (10, 28),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
    )
    
    # Add "Depth Map" label
    cv2.rectangle(labeled_depth, (5, 5), (130, 35), (0, 0, 0), -1)
    cv2.putText(
        labeled_depth, "Depth Map", (10, 28),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )
    
    # Combine horizontally
    combined = np.hstack((labeled_color, labeled_depth))
    
    return combined


def test_realsense_camera():
    """Test RealSense camera functionality."""
    print("=" * 60)
    print("RealSense Camera Test")
    print("=" * 60)
    
    camera = RealSenseCamera(width=640, height=480, fps=30, enable_depth=True)
    
    if not camera.open():
        print("Failed to open camera!")
        return False
    
    info = camera.get_camera_info()
    print(f"\nCamera Info:")
    for key, value in info.items():
        print(f"  {key}: {value}")
    
    print("\nPress 'q' to quit, 's' to save a snapshot...")
    
    frame_count = 0
    while True:
        success, color_frame, depth_raw, depth_colormap = camera.read()
        
        if not success:
            print("Failed to read frame")
            continue
        
        frame_count += 1
        
        # Create combined view
        combined = create_combined_view(color_frame, depth_colormap)
        
        # Add frame counter
        cv2.putText(
            combined, f"Frame: {frame_count}", (10, combined.shape[0] - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
        )
        
        cv2.imshow('RealSense Test - RGB + Depth', combined)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            cv2.imwrite(f'snapshot_{frame_count}.png', combined)
            print(f"Saved snapshot_{frame_count}.png")
    
    camera.release()
    cv2.destroyAllWindows()
    
    print(f"\nTotal frames: {frame_count}")
    return True


if __name__ == "__main__":
    test_realsense_camera()
