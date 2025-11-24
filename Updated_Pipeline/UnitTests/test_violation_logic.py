"""Test NO-Hardhat detection without Person requirement"""

from pipeline.backend.core.violation_detector import ViolationDetector
from pipeline.config import VIOLATION_RULES

# Create detector
detector = ViolationDetector(VIOLATION_RULES)

# Test case 1: NO-Hardhat detected (should trigger)
print("Test 1: NO-Hardhat detected")
detections = [
    {
        'class_name': 'NO-Hardhat',
        'class_id': 8,
        'confidence': 0.14,
        'bbox': [100, 100, 200, 200]
    }
]

result = detector.check_violations(detections)
print(f"  Has violation: {result['has_violation']}")
print(f"  Summary: {result['summary']}")
print(f"  Severity: {result['severity']}")
print(f"  Details: {result['details']}")
print()

# Test case 2: No violations (should not trigger)
print("Test 2: No negative PPE detected")
detections = [
    {
        'class_name': 'Hardhat',
        'class_id': 3,
        'confidence': 0.85,
        'bbox': [100, 100, 200, 200]
    }
]

result = detector.check_violations(detections)
print(f"  Has violation: {result['has_violation']}")
print(f"  Summary: {result['summary']}")
print()

# Test case 3: Multiple NO-Hardhat (should trigger with count)
print("Test 3: Multiple NO-Hardhat detected")
detections = [
    {
        'class_name': 'NO-Hardhat',
        'class_id': 8,
        'confidence': 0.14,
        'bbox': [100, 100, 200, 200]
    },
    {
        'class_name': 'NO-Hardhat',
        'class_id': 8,
        'confidence': 0.22,
        'bbox': [300, 100, 400, 200]
    }
]

result = detector.check_violations(detections)
print(f"  Has violation: {result['has_violation']}")
print(f"  Summary: {result['summary']}")
print(f"  Violation count: {result['violation_count']}")
print()

print("=" * 60)
print("Test complete! If all tests show expected results,")
print("the system should now trigger on NO-Hardhat detection.")
print("=" * 60)
