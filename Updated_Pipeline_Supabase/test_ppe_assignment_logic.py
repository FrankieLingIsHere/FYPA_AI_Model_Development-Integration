
import unittest
from unittest.mock import MagicMock
import logging
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from pipeline.backend.core.report_generator import ReportGenerator

# Disable logging for tests
logging.basicConfig(level=logging.CRITICAL)

class TestPPEAssignment(unittest.TestCase):
    def setUp(self):
        # Mock config
        config = {
            'OLLAMA_CONFIG': {'api_url': 'http://mock'},
            'RAG_CONFIG': {'enabled': False}
        }
        self.generator = ReportGenerator(config=config)

    def test_geometric_ppe_assignment(self):
        # Mock NLP Analysis (2 Persons)
        nlp_analysis = {
            'persons': [
                {'id': 'Person 1', 'description': 'Person on left', 'ppe': {}, 'compliance_status': 'Unknown'},
                {'id': 'Person 2', 'description': 'Person on right', 'ppe': {}, 'compliance_status': 'Unknown'}
            ],
            'environment_type': 'Construction Site',
            'hazards_detected': [],
            'dosh_regulations_cited': []
        }

        # Mock Report Data (YOLO Detections with Bounding Boxes)
        # Person 1: [0, 0, 100, 200] (Left)
        # Person 2: [300, 0, 400, 200] (Right)
        # NO-Hardhat: [10, 10, 50, 50] (Inside Person 1)
        # NO-Vest: [310, 50, 350, 100] (Inside Person 2)
        report_data = {
            'report_id': 'test_report',
            'timestamp': '2026-01-01T12:00:00',
            'detections': [
                {'class_name': 'Person', 'bbox': [300, 0, 400, 200]}, # Person 2 (Right) order shouldn't matter if we sort
                {'class_name': 'Person', 'bbox': [0, 0, 100, 200]},   # Person 1 (Left)
                {'class_name': 'NO-Hardhat', 'bbox': [10, 10, 50, 50]}, # Should trigger Hardhat missing for Person 1
                {'class_name': 'NO-Vest', 'bbox': [310, 50, 350, 100]}  # Should trigger Vest missing for Person 2
            ],
            'violation_count': 2
        }

        # Generate the Person Cards HTML
        # We access the private method to test logic directly
        html_output = self.generator._generate_person_cards_section(nlp_analysis, report_data)
        
        # Check Person 1 (index 0)
        # Should contain "Hardhat: Missing"
        # Should NOT contain "Safety Vest: Missing"
        # We can split by person card? Or simply search using regex/string find with context?
        
        # Easier: The loop iterates "Person 1" then "Person 2".
        # So the first occurrence of "Hardhat:" should be followed by specific status.
        
        print("\n--- Generated HTML Snippet ---")
        # print(html_output) # Uncomment to debug
        
        # We need to verify that Person 1 gets the Hardhat violation
        # and Person 2 gets the Vest violation.
        
        # Split output into person cards
        cards = html_output.split('class="person-card"')
        # cards[0] is header/intro
        # cards[1] should be Person 1 (Leftmost YOLO person mapped to NLP Person 1)
        # cards[2] should be Person 2 (Rightmost YOLO person mapped to NLP Person 2)
        
        if len(cards) < 3:
            self.fail("Did not generate enough person cards")
            
        person1_card = cards[1]
        person2_card = cards[2]
        
        # Check Person 1
        self.assertIn('Person 1', person1_card)
        self.assertIn('Hardhat:</span>', person1_card)
        self.assertIn('ppe-status-missing">Missing</span>', person1_card) # Hardhat missing
        # Verify Vest is NOT missing (Assuming default 'Not Mentioned')
        # We look for "Safety Vest" block
        vest_idx = person1_card.find('Safety Vest:</span>')
        vest_status = person1_card[vest_idx:vest_idx+200]
        self.assertNotIn('ppe-status-missing', vest_status) # Should NOT be missing
        
        # Check Person 2
        self.assertIn('Person 2', person2_card)
        self.assertIn('Safety Vest:</span>', person2_card)
        # Verify Vest IS missing
        status_idx = person2_card.find('Safety Vest:</span>')
        status_sub = person2_card[status_idx:status_idx+200]
        self.assertIn('ppe-status-missing">Missing</span>', status_sub)
        
        # Verify Hardhat is NOT missing for Person 2
        hh_idx = person2_card.find('Hardhat:</span>')
        hh_sub = person2_card[hh_idx:hh_idx+200]
        self.assertNotIn('ppe-status-missing', hh_sub)

        print("Test Passed: Violations correctly assigned to respective persons.")

if __name__ == '__main__':
    unittest.main()
