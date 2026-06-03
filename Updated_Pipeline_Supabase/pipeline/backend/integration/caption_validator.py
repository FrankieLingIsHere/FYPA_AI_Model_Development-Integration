"""
Caption Validator - Cross-check LLaVA captions against YOLO annotations
========================================================================
Validates image captions against detected objects to identify contradictions
and ensure consistency between vision models.

PRIORITY: Focus on PPE items. Person detection is deprioritized because:
- YOLO often misses people without full body visible
- Partial body (just hands, torso) won't be detected as "person"
- PPE items are the critical safety indicators
"""
# Readability: Integration module: isolate external model/provider calls behind stable helpers.

import re
from typing import Dict, List, Tuple, Optional
import logging

# Prepare logger for the next step.
logger = logging.getLogger(__name__)


# Section: group caption validator state and behaviour in one readable unit.
class CaptionValidator:
    """Validates captions against annotations to detect contradictions."""

    # PPE class name mappings - HIGH PRIORITY
    # Prepare ppe classes for the next step.
    PPE_CLASSES = {
        'hardhat': ['helmet', 'hard hat', 'hardhat', 'safety helmet', 'construction helmet'],
        'mask': ['mask', 'face mask', 'respirator', 'protective mask'],
        'safety_vest': ['vest', 'safety vest', 'hi-vis', 'high visibility', 'reflective vest'],
        'gloves': ['glove', 'gloves', 'hand protection', 'safety gloves'],
        'boots': ['boot', 'boots', 'safety boots', 'steel toe', 'work boots'],
    }

    # Person detection - LOW PRIORITY (YOLO often misses partial bodies)
    # Prepare person classes for the next step.
    PERSON_CLASSES = {
        'person': ['person', 'worker', 'individual', 'people', 'human', 'man', 'woman']
    }

    # Negation patterns that indicate absence
    NEGATION_PATTERNS = [
        r'\bnot?\s+wearing\b',
        r'\bwithout\b',
        r'\blacks?\b',
        r'\bmissing\b',
        r'\bno\s+\w+\s+(on|visible)',
        r'\bnone\b',
        r'\babsent\b',
        r'\bfailed\s+to\s+wear\b'
    ]

    # Presence patterns
    # Prepare presence patterns for the next step.
    PRESENCE_PATTERNS = [
        r'\bwearing\b',
        r'\bwith\b',
        r'\bhas\b',
        r'\bequipped\b',
        r'\busing\b',
        r'\bin\s+\w+\s+equipment\b'
    ]

    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self):
        # Prepare logger for the next step.
        self.logger = logger

    # Section: run the validate workflow with clear inputs and outputs.
    def validate(self, caption: str, annotations: List[Dict],
                 detected_classes: List[str]) -> Dict:
        """
        Cross-validate caption against YOLO annotations.

        Args:
            caption: LLaVA generated image caption
            annotations: YOLO detection annotations
            detected_classes: List of class names detected by YOLO

        Returns:
            Dictionary with validation results:
            {
                'is_valid': bool,
                'confidence': float,
                'contradictions': List[str],
                'warnings': List[str],
                'detected_items': Dict[str, bool],
                'caption_mentions': Dict[str, bool]
            }
        """
        # Choose the correct branch before the workflow continues.
        if not caption:
            # Return the prepared result to the caller.
            return {
                'is_valid': False,
                'confidence': 0.0,
                'contradictions': ['Caption is empty'],
                'warnings': [],
                'detected_items': {},
                'caption_mentions': {}
            }

        # Prepare caption lower for the next step.
        caption_lower = caption.lower()

        # Extract what YOLO detected
        detected_items = self._extract_detected_items(detected_classes)

        # Extract what caption mentions
        caption_mentions = self._extract_caption_mentions(caption_lower)

        # Find contradictions (FOCUS ON PPE, not person)
        # Prepare contradictions for the next step.
        contradictions = self._find_contradictions(
            detected_items,
            caption_mentions,
            caption_lower
        )

        # Find warnings (potential issues)
        warnings = self._find_warnings(
            detected_items,
            caption_mentions,
            annotations
        )

        # Calculate confidence score
        # Prepare confidence for the next step.
        confidence = self._calculate_confidence(
            detected_items,
            caption_mentions,
            contradictions,
            warnings
        )

        is_valid = len(contradictions) == 0 and confidence > 0.5

        # Prepare result for the next step.
        result = {
            'is_valid': is_valid,
            'confidence': confidence,
            'contradictions': contradictions,
            'warnings': warnings,
            'detected_items': detected_items,
            'caption_mentions': caption_mentions,
            'validation_summary': self._generate_summary(
                is_valid, confidence, contradictions, warnings
            )
        }

        # Trigger the side effect required for this stage.
        self.logger.info(f"Caption validation: {'PASS' if is_valid else 'FAIL'} "
                        f"(confidence: {confidence:.2f})")
        if contradictions:
            # Trigger the side effect required for this stage.
            self.logger.warning(f"Contradictions found: {contradictions}")

        return result

    # Section: run the extract detected items workflow with clear inputs and outputs.
    def _extract_detected_items(self, detected_classes: List[str]) -> Dict[str, bool]:
        """Extract what items YOLO detected."""
        # Prepare detected for the next step.
        detected = {
            'person': False,
            'hardhat': False,
            'mask': False,
            'safety_vest': False,
            'gloves': False,
            'boots': False
        }

        # Process each item in this collection using the same rule set.
        for cls in detected_classes:
            # Prepare cls lower for the next step.
            cls_lower = cls.lower().replace('-', '_').replace(' ', '_')
            # Direct match
            if cls_lower in detected:
                # Prepare values needed by the next step.
                detected[cls_lower] = True
            # Also check for "no-X" patterns (violation classes)
            elif cls_lower.startswith('no_'):
                # "no_hardhat" means hardhat was NOT detected
                base_class = cls_lower[3:]  # Remove "no_"
                if base_class in detected:
                    detected[base_class] = False

        # Return the prepared result to the caller.
        return detected

    # Section: run the extract caption mentions workflow with clear inputs and outputs.
    def _extract_caption_mentions(self, caption_lower: str) -> Dict[str, Dict]:
        """
        Extract what PPE items the caption mentions and their presence/absence.

        Returns:
            Dict mapping item to {'mentioned': bool, 'present': bool, 'context': str}
        """
        # Prepare mentions for the next step.
        mentions = {}

        # Check PPE items (HIGH PRIORITY)
        for ppe_type, keywords in self.PPE_CLASSES.items():
            mention_data = self._check_item_mention(caption_lower, keywords)
            if mention_data['mentioned']:
                # Prepare values needed by the next step.
                mentions[ppe_type] = mention_data

        # Check person mentions (LOW PRIORITY - just for info)
        # Process each item in this collection using the same rule set.
        for person_type, keywords in self.PERSON_CLASSES.items():
            mention_data = self._check_item_mention(caption_lower, keywords)
            if mention_data['mentioned']:
                mention_data['low_priority'] = True  # Mark as low priority
                mentions[person_type] = mention_data

        return mentions

    # Section: run the check item mention workflow with clear inputs and outputs.
    def _check_item_mention(self, caption_lower: str, keywords: List[str]) -> Dict:
        """Check if any keyword appears in caption and determine presence/absence."""
        # Prepare item found for the next step.
        item_found = False
        is_present = None
        context = ""

        for keyword in keywords:
            # Prepare pattern for the next step.
            pattern = r'\b' + re.escape(keyword) + r's?\b'  # Allow plural
            if re.search(pattern, caption_lower):
                # Prepare item found for the next step.
                item_found = True

                # Extract context (surrounding words)
                match = re.search(r'(\w+\s+){0,5}' + pattern + r'(\s+\w+){0,5}',
                                caption_lower)
                if match:
                    # Prepare context for the next step.
                    context = match.group(0)

                    # Check if negation or presence
                    for neg_pattern in self.NEGATION_PATTERNS:
                        if re.search(neg_pattern, context):
                            is_present = False
                            break

                    if is_present is None:
                        for pos_pattern in self.PRESENCE_PATTERNS:
                            if re.search(pos_pattern, context):
                                # Prepare is present for the next step.
                                is_present = True
                                break

                break

        # Return the prepared result to the caller.
        return {
            'mentioned': item_found,
            'present': is_present,
            'context': context.strip(),
            'low_priority': False
        }

    # Section: run the find contradictions workflow with clear inputs and outputs.
    def _find_contradictions(self, detected_items: Dict[str, bool],
                           caption_mentions: Dict[str, Dict],
                           caption_lower: str) -> List[str]:
        """
        Find contradictions between detections and caption.
        FOCUS ON PPE - person detection is LOW PRIORITY.
        """
        # Prepare contradictions for the next step.
        contradictions = []

        # Check PPE items (HIGH PRIORITY - these are critical)
        ppe_items = ['hardhat', 'mask', 'safety_vest', 'gloves', 'boots']

        for item_type in ppe_items:
            # Prepare detected for the next step.
            detected = detected_items.get(item_type, False)
            mention = caption_mentions.get(item_type)

            if mention and mention['present'] is not None:
                # Caption explicitly states presence/absence
                # Choose the correct branch before the workflow continues.
                if detected and mention['present'] == False:
                    # Trigger the side effect required for this stage.
                    contradictions.append(
                        f"PPE Mismatch: YOLO detected {item_type.replace('_', ' ')} but caption says "
                        f"it's missing: '{mention['context']}'"
                    )
                elif not detected and mention['present'] == True:
                    contradictions.append(
                        f"PPE Mismatch: Caption says {item_type.replace('_', ' ')} is present but "
                        f"YOLO didn't detect it: '{mention['context']}'"
                    )

        # NOTE: Person detection is NOT checked for contradictions
        # YOLO often misses people without full body visible
        # This avoids false positives from partial body detection issues

        return contradictions

    # Section: run the find warnings workflow with clear inputs and outputs.
    def _find_warnings(self, detected_items: Dict[str, bool],
                      caption_mentions: Dict[str, Dict],
                      annotations: List[Dict]) -> List[str]:
        """Find potential issues that aren't outright contradictions."""
        warnings = []

        # Warn if major PPE detected but not mentioned
        # Prepare major ppe for the next step.
        major_ppe = ['hardhat', 'safety_vest', 'mask']
        for ppe in major_ppe:
            if detected_items.get(ppe) and ppe not in caption_mentions:
                # Trigger the side effect required for this stage.
                warnings.append(
                    f"YOLO detected {ppe.replace('_', ' ')} but caption doesn't mention it"
                )

        # Warn if caption mentions PPE ambiguously
        for item_type, mention in caption_mentions.items():
            if item_type == 'person':
                continue  # Skip person - not important
            # Choose the correct branch before the workflow continues.
            if mention['present'] is None:  # Ambiguous mention
                # Trigger the side effect required for this stage.
                warnings.append(
                    f"Caption mentions {item_type.replace('_', ' ')} ambiguously: "
                    f"'{mention['context']}' - unclear if present or absent"
                )

        # Warn if low detection confidence (if available)
        # Choose the correct branch before the workflow continues.
        if annotations:
            low_conf_items = [
                ann for ann in annotations
                if ann.get('confidence', 1.0) < 0.5 and 'person' not in str(ann.get('class', '')).lower()
            ]
            # Choose the correct branch before the workflow continues.
            if low_conf_items:
                # Trigger the side effect required for this stage.
                warnings.append(
                    f"Low confidence PPE detections ({len(low_conf_items)} items below 50%)"
                )

        # NOTE: Person detection issues are NOT flagged as warnings
        # because YOLO commonly misses partial bodies

        return warnings

    # Section: run the calculate confidence workflow with clear inputs and outputs.
    def _calculate_confidence(self, detected_items: Dict[str, bool],
                            caption_mentions: Dict[str, Dict],
                            contradictions: List[str],
                            warnings: List[str]) -> float:
        """
        Calculate validation confidence score (0-1).
        FOCUSES ON PPE AGREEMENT - person detection has minimal weight.
        """
        # Prepare score for the next step.
        score = 1.0

        # Major penalty for contradictions (PPE only)
        score -= len(contradictions) * 0.3

        # Minor penalty for warnings
        score -= len(warnings) * 0.1

        # Bonus for PPE agreement (ONLY PPE, not person)
        # Prepare ppe agreements for the next step.
        ppe_agreements = 0
        ppe_checks = 0

        ppe_items = ['hardhat', 'mask', 'safety_vest', 'gloves', 'boots']

        for item_type in ppe_items:
            # Prepare detected for the next step.
            detected = detected_items.get(item_type, False)
            mention = caption_mentions.get(item_type)

            if mention and mention['present'] is not None:
                ppe_checks += 1
                # Choose the correct branch before the workflow continues.
                if (detected and mention['present']) or \
                   (not detected and not mention['present']):
                    ppe_agreements += 1

        # Choose the correct branch before the workflow continues.
        if ppe_checks > 0:
            # Prepare agreement rate for the next step.
            agreement_rate = ppe_agreements / ppe_checks
            score = score * 0.7 + agreement_rate * 0.3

        return max(0.0, min(1.0, score))

    # Section: run the generate summary workflow with clear inputs and outputs.
    def _generate_summary(self, is_valid: bool, confidence: float,
                         contradictions: List[str], warnings: List[str]) -> str:
        """Generate human-readable validation summary."""
        # Choose the correct branch before the workflow continues.
        if is_valid and confidence > 0.8:
            # Return the prepared result to the caller.
            return "PPE caption matches annotations with high confidence"
        elif is_valid:
            summary = f"PPE caption generally matches (confidence: {confidence:.0%})"
            if warnings:
                summary += f" but {len(warnings)} warning(s) noted"
            return summary
        else:
            summary = f"PPE validation failed ({len(contradictions)} contradiction(s))"
            if confidence > 0.3:
                summary += " - caption partially accurate"
            else:
                summary += " - significant PPE discrepancies"
            # Return the prepared result to the caller.
            return summary


# Section: run the validate caption workflow with clear inputs and outputs.
def validate_caption(caption: str, annotations: List[Dict],
                    detected_classes: List[str]) -> Dict:
    """
    Convenience function to validate caption.

    Args:
        caption: LLaVA generated caption
        annotations: YOLO detection results
        detected_classes: List of detected class names

    Returns:
        Validation result dictionary
    """
    # Prepare validator for the next step.
    validator = CaptionValidator()
    return validator.validate(caption, annotations, detected_classes)
