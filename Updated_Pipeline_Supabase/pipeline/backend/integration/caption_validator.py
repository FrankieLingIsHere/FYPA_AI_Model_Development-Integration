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

import re
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class CaptionValidator:
    """Validates captions against annotations to detect contradictions."""
    
    # PPE class name mappings - HIGH PRIORITY
    PPE_CLASSES = {
        'hardhat': ['helmet', 'hard hat', 'hardhat', 'safety helmet', 'construction helmet'],
        'mask': ['mask', 'face mask', 'respirator', 'protective mask'],
        'safety_vest': ['vest', 'safety vest', 'hi-vis', 'high visibility', 'reflective vest'],
        'gloves': ['glove', 'gloves', 'hand protection', 'safety gloves'],
        'goggles': ['goggles', 'safety glasses', 'eye protection', 'protective eyewear'],
        'boots': ['boot', 'boots', 'safety boots', 'steel toe', 'work boots'],
    }
    
    # Person detection - LOW PRIORITY (YOLO often misses partial bodies)
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
    PRESENCE_PATTERNS = [
        r'\bwearing\b',
        r'\bwith\b',
        r'\bhas\b',
        r'\bequipped\b',
        r'\busing\b',
        r'\bin\s+\w+\s+equipment\b'
    ]
    
    def __init__(self):
        self.logger = logger
        
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
        if not caption:
            return {
                'is_valid': False,
                'confidence': 0.0,
                'contradictions': ['Caption is empty'],
                'warnings': [],
                'detected_items': {},
                'caption_mentions': {}
            }
            
        caption_lower = caption.lower()
        
        # Extract what YOLO detected
        detected_items = self._extract_detected_items(detected_classes)
        
        # Extract what caption mentions
        caption_mentions = self._extract_caption_mentions(caption_lower)
        
        # Find contradictions (FOCUS ON PPE, not person)
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
        confidence = self._calculate_confidence(
            detected_items,
            caption_mentions,
            contradictions,
            warnings
        )
        
        is_valid = len(contradictions) == 0 and confidence > 0.5
        
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
        
        self.logger.info(f"Caption validation: {'PASS' if is_valid else 'FAIL'} "
                        f"(confidence: {confidence:.2f})")
        if contradictions:
            self.logger.warning(f"Contradictions found: {contradictions}")
            
        return result
    
    def _extract_detected_items(self, detected_classes: List[str]) -> Dict[str, bool]:
        """Extract what items YOLO detected."""
        detected = {
            'person': False,
            'hardhat': False,
            'mask': False,
            'safety_vest': False,
            'gloves': False,
            'goggles': False,
            'boots': False
        }
        
        for cls in detected_classes:
            cls_lower = cls.lower().replace('-', '_').replace(' ', '_')
            # Direct match
            if cls_lower in detected:
                detected[cls_lower] = True
            # Also check for "no-X" patterns (violation classes)
            elif cls_lower.startswith('no_'):
                # "no_hardhat" means hardhat was NOT detected
                base_class = cls_lower[3:]  # Remove "no_"
                if base_class in detected:
                    detected[base_class] = False
                
        return detected
    
    def _extract_caption_mentions(self, caption_lower: str) -> Dict[str, Dict]:
        """
        Extract what PPE items the caption mentions and their presence/absence.
        
        Returns:
            Dict mapping item to {'mentioned': bool, 'present': bool, 'context': str}
        """
        mentions = {}
        
        # Check PPE items (HIGH PRIORITY)
        for ppe_type, keywords in self.PPE_CLASSES.items():
            mention_data = self._check_item_mention(caption_lower, keywords)
            if mention_data['mentioned']:
                mentions[ppe_type] = mention_data
        
        # Check person mentions (LOW PRIORITY - just for info)
        for person_type, keywords in self.PERSON_CLASSES.items():
            mention_data = self._check_item_mention(caption_lower, keywords)
            if mention_data['mentioned']:
                mention_data['low_priority'] = True  # Mark as low priority
                mentions[person_type] = mention_data
        
        return mentions
    
    def _check_item_mention(self, caption_lower: str, keywords: List[str]) -> Dict:
        """Check if any keyword appears in caption and determine presence/absence."""
        item_found = False
        is_present = None
        context = ""
        
        for keyword in keywords:
            pattern = r'\b' + re.escape(keyword) + r's?\b'  # Allow plural
            if re.search(pattern, caption_lower):
                item_found = True
                
                # Extract context (surrounding words)
                match = re.search(r'(\w+\s+){0,5}' + pattern + r'(\s+\w+){0,5}', 
                                caption_lower)
                if match:
                    context = match.group(0)
                    
                    # Check if negation or presence
                    for neg_pattern in self.NEGATION_PATTERNS:
                        if re.search(neg_pattern, context):
                            is_present = False
                            break
                    
                    if is_present is None:
                        for pos_pattern in self.PRESENCE_PATTERNS:
                            if re.search(pos_pattern, context):
                                is_present = True
                                break
                
                break
        
        return {
            'mentioned': item_found,
            'present': is_present,
            'context': context.strip(),
            'low_priority': False
        }
    
    def _find_contradictions(self, detected_items: Dict[str, bool],
                           caption_mentions: Dict[str, Dict],
                           caption_lower: str) -> List[str]:
        """
        Find contradictions between detections and caption.
        FOCUS ON PPE - person detection is LOW PRIORITY.
        """
        contradictions = []
        
        # Check PPE items (HIGH PRIORITY - these are critical)
        ppe_items = ['hardhat', 'mask', 'safety_vest', 'gloves', 'goggles', 'boots']
        
        for item_type in ppe_items:
            detected = detected_items.get(item_type, False)
            mention = caption_mentions.get(item_type)
            
            if mention and mention['present'] is not None:
                # Caption explicitly states presence/absence
                if detected and mention['present'] == False:
                    contradictions.append(
                        f"⚠️ PPE Mismatch: YOLO detected {item_type.replace('_', ' ')} but caption says "
                        f"it's missing: '{mention['context']}'"
                    )
                elif not detected and mention['present'] == True:
                    contradictions.append(
                        f"⚠️ PPE Mismatch: Caption says {item_type.replace('_', ' ')} is present but "
                        f"YOLO didn't detect it: '{mention['context']}'"
                    )
        
        # NOTE: Person detection is NOT checked for contradictions
        # YOLO often misses people without full body visible
        # This avoids false positives from partial body detection issues
        
        return contradictions
    
    def _find_warnings(self, detected_items: Dict[str, bool],
                      caption_mentions: Dict[str, Dict],
                      annotations: List[Dict]) -> List[str]:
        """Find potential issues that aren't outright contradictions."""
        warnings = []
        
        # Warn if major PPE detected but not mentioned
        major_ppe = ['hardhat', 'safety_vest', 'mask']
        for ppe in major_ppe:
            if detected_items.get(ppe) and ppe not in caption_mentions:
                warnings.append(
                    f"YOLO detected {ppe.replace('_', ' ')} but caption doesn't mention it"
                )
        
        # Warn if caption mentions PPE ambiguously
        for item_type, mention in caption_mentions.items():
            if item_type == 'person':
                continue  # Skip person - not important
            if mention['present'] is None:  # Ambiguous mention
                warnings.append(
                    f"Caption mentions {item_type.replace('_', ' ')} ambiguously: "
                    f"'{mention['context']}' - unclear if present or absent"
                )
        
        # Warn if low detection confidence (if available)
        if annotations:
            low_conf_items = [
                ann for ann in annotations 
                if ann.get('confidence', 1.0) < 0.5 and 'person' not in str(ann.get('class', '')).lower()
            ]
            if low_conf_items:
                warnings.append(
                    f"Low confidence PPE detections ({len(low_conf_items)} items below 50%)"
                )
        
        # NOTE: Person detection issues are NOT flagged as warnings
        # because YOLO commonly misses partial bodies
        
        return warnings
    
    def _calculate_confidence(self, detected_items: Dict[str, bool],
                            caption_mentions: Dict[str, Dict],
                            contradictions: List[str],
                            warnings: List[str]) -> float:
        """
        Calculate validation confidence score (0-1).
        FOCUSES ON PPE AGREEMENT - person detection has minimal weight.
        """
        score = 1.0
        
        # Major penalty for contradictions (PPE only)
        score -= len(contradictions) * 0.3
        
        # Minor penalty for warnings
        score -= len(warnings) * 0.1
        
        # Bonus for PPE agreement (ONLY PPE, not person)
        ppe_agreements = 0
        ppe_checks = 0
        
        ppe_items = ['hardhat', 'mask', 'safety_vest', 'gloves', 'goggles', 'boots']
        
        for item_type in ppe_items:
            detected = detected_items.get(item_type, False)
            mention = caption_mentions.get(item_type)
            
            if mention and mention['present'] is not None:
                ppe_checks += 1
                if (detected and mention['present']) or \
                   (not detected and not mention['present']):
                    ppe_agreements += 1
        
        if ppe_checks > 0:
            agreement_rate = ppe_agreements / ppe_checks
            score = score * 0.7 + agreement_rate * 0.3
        
        return max(0.0, min(1.0, score))
    
    def _generate_summary(self, is_valid: bool, confidence: float,
                         contradictions: List[str], warnings: List[str]) -> str:
        """Generate human-readable validation summary."""
        if is_valid and confidence > 0.8:
            return "✅ PPE caption matches annotations with high confidence"
        elif is_valid:
            summary = f"✅ PPE caption generally matches (confidence: {confidence:.0%})"
            if warnings:
                summary += f" but {len(warnings)} warning(s) noted"
            return summary
        else:
            summary = f"❌ PPE validation failed ({len(contradictions)} contradiction(s))"
            if confidence > 0.3:
                summary += " - caption partially accurate"
            else:
                summary += " - significant PPE discrepancies"
            return summary


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
    validator = CaptionValidator()
    return validator.validate(caption, annotations, detected_classes)
