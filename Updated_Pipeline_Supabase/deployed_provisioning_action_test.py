import os
import sys
import unittest
import json
import time

# Ensure we can import luna_app
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Set test environment to skip hardware checks
os.environ['FLASK_DEBUG'] = 'false'
os.environ['SERVE_FRONTEND'] = 'false'
os.environ['ADMIN_PASSWORD'] = 'test-magic-password'
os.environ['SUPABASE_DB_URL'] = 'postgres://test:test@localhost:5432/test'

from luna_app import app, _load_pending_devices, PENDING_DEVICES_FILE

class ProvisioningActionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a test client
        cls.client = app.test_client()
        # Clean up any existing state
        if PENDING_DEVICES_FILE.exists():
            PENDING_DEVICES_FILE.unlink()
            
    @classmethod
    def tearDownClass(cls):
        if PENDING_DEVICES_FILE.exists():
            PENDING_DEVICES_FILE.unlink()
            
    def test_magic_link_provisioning_flow(self):
        print("\n[+] Testing Edge Node Request Generation...")
        machine_id = "TEST-EDGE-9999"
        
        # 1. Simulate edge node requesting access
        response = self.client.post('/api/provision/request', json={"machine_id": machine_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json.get("status"), "stored")
        
        # 2. Verify status is pending
        status_response = self.client.get(f'/api/provision/status?machine_id={machine_id}')
        self.assertEqual(status_response.json.get("status"), "pending")
        
        # 3. Extract the magic token from the queue (simulating email delivery)
        print("[+] Extracting secure token simulating Email receipt...")
        devices = _load_pending_devices()
        self.assertIn(machine_id, devices)
        token = devices[machine_id].get("token")
        self.assertIsNotNone(token, "Approval token was not generated!")
        
        # 4. Access the Magic Link (Requires Basic Auth per our constraints)
        print("[+] Accessing Magic Link protected via Basic Auth...")
        headers = {}
        # We must provide the correct auth to simulate the browser
        import base64
        auth_string = base64.b64encode(b"admin:test-magic-password").decode('utf-8')
        headers['Authorization'] = f"Basic {auth_string}"
        
        magic_response = self.client.get(f'/admin/devices/quick-approve?machine_id={machine_id}&token={token}', headers=headers)
        self.assertEqual(magic_response.status_code, 200)
        self.assertIn(b"Approved Successfully", magic_response.data)
        
        # 5. Verify the edge node completes polling successfully
        print("[+] Edge node polling status...")
        final_status = self.client.get(f'/api/provision/status?machine_id={machine_id}')
        self.assertEqual(final_status.json.get("status"), "approved")
        
        # 6. Ensure credentials were securely passed down
        credentials = final_status.json.get("credentials", {})
        self.assertIn("SUPABASE_DB_URL", credentials)
        self.assertTrue(credentials.get("SUPABASE_DB_URL").startswith("postgres"))
        print("[✔] COMPLETE: Magic Approval Link successfully provisioned the edge device.")

if __name__ == '__main__':
    unittest.main()
