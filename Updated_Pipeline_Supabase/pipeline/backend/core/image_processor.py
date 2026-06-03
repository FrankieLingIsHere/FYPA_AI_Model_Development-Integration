"""
Image Processor - Wrapper for image inference and annotation
=============================================================

Integrates existing inference code from gui_infer.py
Handles:
- Image preprocessing
- YOLO inference on static images
- Frame annotation with bounding boxes
- Detection metadata extraction

Usage:
    processor = ImageProcessor(config)
    detections, annotated = processor.process_image(frame)
    annotated_frame = processor.annotate_frame(frame, detections)
"""
# Readability: Backend core: coordinate detection, persistence, and report workflow concerns.

import logging
import cv2
import numpy as np
from typing import List, Dict, Any, Tuple, Union, Optional
from pathlib import Path
import sys

# Import existing inference module
# Trigger the side effect required for this stage.
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.absolute()))

try:
    from infer_image import predict_image
    # Prepare infer available for the next step.
    INFER_AVAILABLE = True
except ImportError:
    INFER_AVAILABLE = False
    logging.warning("infer_image module not available")

# Prepare logger for the next step.
logger = logging.getLogger(__name__)


# Section: group image processor state and behaviour in one readable unit.
class ImageProcessor:
    """
    Processes images for violation detection.
    
    Wraps existing inference code and provides annotation capabilities.
    """
    
    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize image processor.
        
        Args:
            config: Configuration dictionary from config.py
        """
        # Prepare config for the next step.
        self.config = config
        
        # YOLO settings
        yolo_config = config.get('YOLO_CONFIG', {})
        self.model_path = yolo_config.get('model_path', 'yolov8s.pt')
        self.conf_threshold = yolo_config.get('conf_threshold', 0.10)
        
        # Class names and colors
        self.class_names = config.get('PPE_CLASSES', {})
        self.colors = self._generate_colors(len(self.class_names))
        
        logger.info("Image Processor initialized")
    
    # Section: run the generate colors workflow with clear inputs and outputs.
    def _generate_colors(self, num_classes: int) -> Dict[int, Tuple[int, int, int]]:
        """Generate distinct colors for each class."""
        colors = {}
        np.random.seed(42)  # Consistent colors
        
        # Process each item in this collection using the same rule set.
        for class_id in range(num_classes):
            # Prepare values needed by the next step.
            colors[class_id] = tuple(map(int, np.random.randint(0, 255, 3)))
        
        return colors
    
    # =========================================================================
    # IMAGE PROCESSING
    # =========================================================================
    
    def process_image(
        self,
        image: Union[str, np.ndarray, bytes],
        model_path: Optional[str] = None,
        conf: Optional[float] = None
    ) -> Tuple[List[Dict[str, Any]], np.ndarray]:
        """
        Process an image and return detections with annotated image.
        
        Uses the existing infer_image.predict_image function.
        
        Args:
            image: Image path, numpy array, or bytes
            model_path: Optional model path override
            conf: Optional confidence threshold override
        
        Returns:
            Tuple of (detections, annotated_image)
        """
        # Choose the correct branch before the workflow continues.
        if not INFER_AVAILABLE:
            # Trigger the side effect required for this stage.
            logger.error("infer_image module not available")
            # Fallback: return empty detections and original image
            if isinstance(image, np.ndarray):
                # Return the prepared result to the caller.
                return [], image.copy()
            return [], None
        
        model_path = model_path or self.model_path
        conf = conf or self.conf_threshold
        
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare values needed by the next step.
            detections, annotated = predict_image(
                image,
                model_path=model_path,
                conf=conf
            )
            
            logger.debug(f"Processed image: {len(detections)} detections")
            return detections, annotated
            
        except Exception as e:
            # Trigger the side effect required for this stage.
            logger.error(f"Error processing image: {e}", exc_info=True)
            # Return empty detections and original image if available
            if isinstance(image, np.ndarray):
                # Return the prepared result to the caller.
                return [], image.copy()
            return [], None
    
    # Section: run the annotate frame workflow with clear inputs and outputs.
    def annotate_frame(
        self,
        frame: np.ndarray,
        detections: List[Dict[str, Any]],
        show_confidence: bool = True,
        thickness: int = 2
    ) -> np.ndarray:
        """
        Annotate a frame with detection bounding boxes and labels.
        
        Args:
            frame: Input frame
            detections: List of detection dictionaries
            show_confidence: Whether to show confidence scores
            thickness: Line thickness for boxes
        
        Returns:
            Annotated frame
        """
        # Prepare annotated for the next step.
        annotated = frame.copy()
        
        for det in detections:
            # Get box coordinates
            # Prepare bbox for the next step.
            bbox = det['bbox']
            x1, y1, x2, y2 = map(int, bbox)
            
            # Get class info
            class_id = det.get('class_id', 0)
            class_name = det.get('class_name', 'Unknown')
            confidence = det.get('confidence', 0.0)
            
            # Get color for this class
            # Prepare color for the next step.
            color = self.colors.get(class_id, (0, 255, 0))
            
            # Draw bounding box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)
            
            # Prepare label
            if show_confidence:
                label = f"{class_name} {confidence:.2f}"
            else:
                label = class_name
            
            # Draw label background
            # Prepare values needed by the next step.
            (label_width, label_height), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            
            # Make sure label doesn't go off screen
            y_label = max(y1 - 10, label_height + 10)
            
            cv2.rectangle(
                annotated,
                (x1, y_label - label_height - baseline),
                (x1 + label_width, y_label + baseline),
                color,
                -1  # Filled
            )
            
            # Draw label text
            # Trigger the side effect required for this stage.
            cv2.putText(
                annotated,
                label,
                (x1, y_label - baseline),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),  # White text
                1,
                cv2.LINE_AA
            )
        
        # Return the prepared result to the caller.
        return annotated
    
    # Section: run the add info overlay workflow with clear inputs and outputs.
    def add_info_overlay(
        self,
        frame: np.ndarray,
        info: Dict[str, Any]
    ) -> np.ndarray:
        """
        Add information overlay to frame (e.g., FPS, violation count).
        
        Args:
            frame: Input frame
            info: Dictionary with info to display
        
        Returns:
            Frame with overlay
        """
        # Prepare overlay for the next step.
        overlay = frame.copy()
        height, width = overlay.shape[:2]
        
        # Semi-transparent background for text
        overlay_bg = overlay.copy()
        cv2.rectangle(
            overlay_bg,
            (10, 10),
            (300, 100),
            (0, 0, 0),
            -1
        )
        # Trigger the side effect required for this stage.
        cv2.addWeighted(overlay_bg, 0.6, overlay, 0.4, 0, overlay)
        
        # Add text
        y_offset = 30
        for key, value in info.items():
            text = f"{key}: {value}"
            cv2.putText(
                overlay,
                text,
                (20, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA
            )
            y_offset += 25
        
        # Return the prepared result to the caller.
        return overlay
    
    # =========================================================================
    # UTILITY FUNCTIONS
    # =========================================================================
    
    def resize_frame(
        self,
        frame: np.ndarray,
        max_width: int = 1920,
        max_height: int = 1080
    ) -> np.ndarray:
        """
        Resize frame maintaining aspect ratio.
        
        Args:
            frame: Input frame
            max_width: Maximum width
            max_height: Maximum height
        
        Returns:
            Resized frame
        """
        # Prepare values needed by the next step.
        height, width = frame.shape[:2]
        
        # Calculate scale
        scale = min(max_width / width, max_height / height, 1.0)
        
        if scale < 1.0:
            # Prepare new width for the next step.
            new_width = int(width * scale)
            new_height = int(height * scale)
            return cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
        
        # Return the prepared result to the caller.
        return frame
    
    # Section: run the save image workflow with clear inputs and outputs.
    def save_image(
        self,
        image: np.ndarray,
        path: Union[str, Path],
        quality: int = 95
    ) -> bool:
        """
        Save image to disk.
        
        Args:
            image: Image to save
            path: Output path
            quality: JPEG quality (1-100)
        
        Returns:
            True if successful
        """
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare path for the next step.
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            cv2.imwrite(
                str(path),
                image,
                [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            
            # Trigger the side effect required for this stage.
            logger.debug(f"Image saved: {path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving image: {e}")
            return False


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    import sys
    from pathlib import Path
    # Trigger the side effect required for this stage.
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.absolute()))
    from config import YOLO_CONFIG, PPE_CLASSES
    
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 70)
    print("IMAGE PROCESSOR TEST")
    print("=" * 70)
    
    # Create config
    # Prepare config for the next step.
    config = {
        'YOLO_CONFIG': YOLO_CONFIG,
        'PPE_CLASSES': PPE_CLASSES
    }
    
    # Create processor
    processor = ImageProcessor(config)
    
    print(f"\n[OK] Image Processor initialized")
    # Trigger the side effect required for this stage.
    print(f"Model path: {processor.model_path}")
    print(f"Confidence threshold: {processor.conf_threshold}")
    print(f"Classes: {len(processor.class_names)}")
    print(f"infer_image available: {INFER_AVAILABLE}")
    
    # Test with dummy frame
    print("\n--- Testing Annotation ---")
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    
    # Prepare dummy detections for the next step.
    dummy_detections = [
        {
            'class_id': 3,
            'class_name': 'Hardhat',
            'confidence': 0.95,
            'bbox': [100, 100, 200, 200]
        },
        {
            'class_id': 11,
            'class_name': 'Person',
            'confidence': 0.88,
            'bbox': [150, 150, 350, 450]
        }
    ]
    
    # Prepare annotated for the next step.
    annotated = processor.annotate_frame(dummy_frame, dummy_detections)
    print(f"[OK] Annotated frame shape: {annotated.shape}")
    
    # Test info overlay
    info = {'FPS': 30, 'Detections': 2, 'Status': 'Active'}
    with_overlay = processor.add_info_overlay(annotated, info)
    print(f"[OK] Frame with overlay shape: {with_overlay.shape}")
    
    print("\n[OK] All tests passed!")
    # Trigger the side effect required for this stage.
    print("=" * 70)
