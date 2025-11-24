"""
Violation Detection Engine
==========================
Core logic for detecting PPE violations from YOLO detections.
Handles person-PPE association and violation rule checking.
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Detection:
    """Represents a single YOLO detection."""
    bbox: List[int]  # [x1, y1, x2, y2]
    confidence: float
    class_name: str
    class_id: int
    
    @property
    def center(self) -> Tuple[float, float]:
        """Get the center point of the bounding box."""
        return ((self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2)
    
    @property
    def area(self) -> float:
        """Get the area of the bounding box."""
        return (self.bbox[2] - self.bbox[0]) * (self.bbox[3] - self.bbox[1])


@dataclass
class PersonDetection:
    """Represents a person and their associated PPE."""
    detection: Detection
    ppe_items: Dict[str, List[Detection]] = field(default_factory=dict)
    violations: List[str] = field(default_factory=list)
    
    def has_ppe(self, ppe_type: str) -> bool:
        """Check if person has a specific PPE type."""
        return ppe_type in self.ppe_items and len(self.ppe_items[ppe_type]) > 0
    
    def has_violation(self) -> bool:
        """Check if person has any violations."""
        return len(self.violations) > 0


@dataclass
class ViolationEvent:
    """Represents a complete violation event."""
    persons: List[PersonDetection]
    all_detections: List[Detection]
    frame: np.ndarray  # Original frame
    timestamp: str
    violation_summary: List[str] = field(default_factory=list)
    
    def has_violations(self) -> bool:
        """Check if event contains any violations."""
        return any(person.has_violation() for person in self.persons)

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def calculate_iou(boxA: List[int], boxB: List[int]) -> float:
    """
    Calculate Intersection over Union (IoU) between two boxes.
    
    Args:
        boxA, boxB: Bounding boxes in format [x1, y1, x2, y2]
    
    Returns:
        IoU value between 0 and 1
    """
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    
    interArea = max(0, xB - xA) * max(0, yB - yA)
    
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    
    iou = interArea / float(boxAArea + boxBArea - interArea) if (boxAArea + boxBArea - interArea) > 0 else 0
    return iou


def is_within_or_near(ppe_bbox: List[int], person_bbox: List[int], threshold: float = 0.3) -> bool:
    """
    Check if PPE bounding box is within or near a person's bounding box.
    
    Uses IoU and also checks if PPE center is within person bbox.
    """
    iou = calculate_iou(ppe_bbox, person_bbox)
    if iou > threshold:
        return True
    
    # Check if PPE center is within person bbox
    ppe_center_x = (ppe_bbox[0] + ppe_bbox[2]) / 2
    ppe_center_y = (ppe_bbox[1] + ppe_bbox[3]) / 2
    
    if (person_bbox[0] <= ppe_center_x <= person_bbox[2] and
        person_bbox[1] <= ppe_center_y <= person_bbox[3]):
        return True
    
    return False


def normalize_class_name(name: str) -> str:
    """Normalize class name for consistent matching."""
    return ''.join(ch for ch in name.lower() if ch.isalnum())

# =============================================================================
# VIOLATION DETECTION LOGIC
# =============================================================================

class ViolationDetector:
    """
    Main violation detection engine.
    
    Processes YOLO detections and identifies PPE violations based on
    configurable rules.
    """
    
    def __init__(self, violation_rules: Dict):
        """
        Initialize the violation detector.
        
        Args:
            violation_rules: Violation rules from config (VIOLATION_RULES)
        """
        # Extract required PPE from rules
        required_ppe_rules = violation_rules.get('required_ppe', {})
        self.required_ppe = {
            ppe_name: ppe_config['negative_class']
            for ppe_name, ppe_config in required_ppe_rules.items()
        }
        
        # Get thresholds
        self.iou_threshold = violation_rules.get('person_ppe_iou_threshold', 0.3)
        self.person_conf_threshold = violation_rules.get('person_confidence_threshold', 0.25)
        
        # Critical violations (like Fall Detection)
        self.critical_violations = violation_rules.get('critical', {})
        
        logger.info(f"ViolationDetector initialized with {len(self.required_ppe)} required PPE types")
        logger.info(f"Required PPE: {list(self.required_ppe.keys())}")
        logger.info(f"Critical violations: {list(self.critical_violations.keys())}")
    
    def check_violations(self, detections: List[Dict]) -> Dict[str, any]:
        """
        Check for violations in detections (simplified interface for orchestrator).
        
        Args:
            detections: Raw detection list from YOLO
        
        Returns:
            Dictionary with:
                - has_violation: bool
                - summary: str
                - person_count: int
                - violation_count: int
                - severity: str
                - details: list
        """
        # Check for critical violations first (Fall Detection)
        for det in detections:
            class_name = det.get('class_name', '')
            if class_name in self.critical_violations:
                return {
                    'has_violation': True,
                    'summary': f'CRITICAL: {class_name} detected',
                    'person_count': sum(1 for d in detections if 'person' in d.get('class_name', '').lower()),
                    'violation_count': 1,
                    'severity': 'CRITICAL',
                    'details': [self.critical_violations[class_name]['description']]
                }
        
        # NEW: Check for negative PPE classes directly (no person required)
        violation_details = []
        violation_count = 0
        severity = 'NONE'
        
        for det in detections:
            class_name = det.get('class_name', '')
            # Check if this is a negative PPE class we care about
            for required_ppe, negative_class in self.required_ppe.items():
                if class_name == negative_class:
                    violation_details.append(f"Missing {required_ppe}")
                    violation_count += 1
                    severity = 'HIGH'
        
        has_violation = violation_count > 0
        
        if has_violation:
            summary = f"{violation_count} PPE violation(s) detected: {', '.join(violation_details)}"
        else:
            summary = "No violations detected"
        
        return {
            'has_violation': has_violation,
            'summary': summary,
            'person_count': 0,  # Not tracking persons anymore
            'violation_count': violation_count,
            'severity': severity,
            'details': violation_details
        }
    
    def parse_detections(self, detections: List[Dict]) -> Tuple[List[Detection], List[Detection]]:
        """
        Parse raw detections into person and PPE categories.
        
        Args:
            detections: List of detection dicts from YOLO
        
        Returns:
            Tuple of (person_detections, ppe_detections)
        """
        persons = []
        ppe = []
        
        for det in detections:
            detection = Detection(
                bbox=det['bbox'],
                confidence=det['confidence'],  # Fixed: was 'score', should be 'confidence'
                class_name=det['class_name'],
                class_id=det['class_id']
            )
            
            # Normalize class name for comparison
            norm_name = normalize_class_name(detection.class_name)
            
            if 'person' in norm_name:
                if detection.confidence >= self.person_conf_threshold:
                    persons.append(detection)
                    logger.debug(f"Person detected with confidence {detection.confidence:.2f}")
            else:
                ppe.append(detection)
                logger.debug(f"PPE detected: {detection.class_name} ({detection.confidence:.2f})")
        
        return persons, ppe
    
    def check_ppe_violations(self, person_objects: List[PersonDetection]) -> List[PersonDetection]:
        """
        Check each person for PPE violations based on rules.
        
        Args:
            person_objects: List of PersonDetection objects with associated PPE
        
        Returns:
            Same list with violations populated
        """
        for person_obj in person_objects:
            for required, negative in self.required_ppe.items():
                # Check if person has the required PPE
                has_positive = person_obj.has_ppe(required)
                has_negative = person_obj.has_ppe(negative)
                
                # Violation if:
                # 1. Missing both positive and negative (ambiguous, assume violation)
                # 2. Has explicit negative detection
                if has_negative or (not has_positive and not has_negative):
                    violation_msg = f"Missing {required}"
                    person_obj.violations.append(violation_msg)
                    logger.warning(f"Violation detected: {violation_msg} at bbox {person_obj.detection.bbox}")
        
        return person_objects
    
    def associate_ppe_with_persons(self, persons: List[Detection], 
                                   ppe: List[Detection]) -> List[PersonDetection]:
        """
        Associate PPE detections with person detections.
        
        Args:
            persons: List of person detections
            ppe: List of PPE detections
        
        Returns:
            List of PersonDetection objects with associated PPE
        """
        person_objects = []
        
        for person in persons:
            person_obj = PersonDetection(detection=person)
            
            # Find all PPE items associated with this person
            for ppe_item in ppe:
                if is_within_or_near(ppe_item.bbox, person.bbox, self.iou_threshold):
                    class_name = ppe_item.class_name
                    
                    if class_name not in person_obj.ppe_items:
                        person_obj.ppe_items[class_name] = []
                    
                    person_obj.ppe_items[class_name].append(ppe_item)
                    logger.debug(f"Associated {class_name} with person at {person.bbox}")
            
            person_objects.append(person_obj)
        
        return person_objects
    
    def detect_violations(self, detections: List[Dict], frame: np.ndarray, 
                         timestamp: str) -> Optional[ViolationEvent]:
        """
        Main entry point: detect violations from raw YOLO detections.
        
        Args:
            detections: Raw detection list from YOLO
            frame: Original video frame (numpy array)
            timestamp: Timestamp string
        
        Returns:
            ViolationEvent if violations found, None otherwise
        """
        if not detections:
            logger.debug("No detections in frame")
            return None
        
        # Parse detections
        persons, ppe = self.parse_detections(detections)
        
        if not persons:
            logger.debug("No persons detected in frame")
            return None
        
        logger.info(f"Frame analysis: {len(persons)} persons, {len(ppe)} PPE items")
        
        # Associate PPE with persons
        person_objects = self.associate_ppe_with_persons(persons, ppe)
        
        # Check for violations
        person_objects = self.check_violations(person_objects)
        
        # Create violation event
        violation_summary = []
        for i, person in enumerate(person_objects, 1):
            if person.has_violation():
                violation_summary.append(f"Person {i}: {', '.join(person.violations)}")
        
        if violation_summary:
            event = ViolationEvent(
                persons=person_objects,
                all_detections=[Detection(**det) for det in detections],
                frame=frame,
                timestamp=timestamp,
                violation_summary=violation_summary
            )
            logger.info(f"Violation event created with {len(violation_summary)} violations")
            return event
        
        logger.debug("No violations detected in frame")
        return None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_violation_summary_text(event: ViolationEvent) -> str:
    """Generate a human-readable summary of violations."""
    lines = [
        f"Violation detected at {event.timestamp}",
        f"Total persons: {len(event.persons)}",
        f"Persons with violations: {sum(1 for p in event.persons if p.has_violation())}",
        "",
        "Violation Details:",
    ]
    
    for i, person in enumerate(event.persons, 1):
        if person.has_violation():
            lines.append(f"  Person {i}:")
            for violation in person.violations:
                lines.append(f"    - {violation}")
            lines.append(f"    PPE detected: {', '.join(person.ppe_items.keys()) if person.ppe_items else 'None'}")
    
    return "\n".join(lines)


if __name__ == '__main__':
    # Test the module
    logging.basicConfig(level=logging.DEBUG)
    
    # Example configuration
    required_ppe = {
        'Hardhat': 'NO-Hardhat',
        'Safety Vest': 'NO-Safety Vest',
    }
    
    detector = ViolationDetector(required_ppe)
    
    # Example detections
    test_detections = [
        {'bbox': [100, 100, 200, 300], 'score': 0.9, 'class_name': 'Person', 'class_id': 0},
        {'bbox': [120, 120, 180, 160], 'score': 0.7, 'class_name': 'NO-Hardhat', 'class_id': 1},
    ]
    
    test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    event = detector.detect_violations(test_detections, test_frame, "2025-11-05 10:30:00")
    
    if event:
        print(get_violation_summary_text(event))
    else:
        print("No violations detected")
