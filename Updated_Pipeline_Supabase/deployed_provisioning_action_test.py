import os
import sys
import unittest
import base64

# Ensure we can import luna_app
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Test environment setup
os.environ['FLASK_DEBUG'] = 'false'
os.environ['SERVE_FRONTEND'] = 'false'
os.environ['ADMIN_PASSWORD'] = 'test-magic-password'
os.environ['BOOTSTRAP_TOKEN_SECRET'] = 'test-bootstrap-secret'
os.environ['SUPABASE_DB_URL'] = 'postgres://test:test@localhost:5432/test'
os.environ['SUPABASE_URL'] = 'https://example.supabase.co'
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = 'service-role-test-key'

from luna_app import app, _load_pending_devices, PENDING_DEVICES_FILE, BOOTSTRAP_TOKEN_STATE_FILE


class ProvisioningActionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def setUp(self):
        if PENDING_DEVICES_FILE.exists():
            PENDING_DEVICES_FILE.unlink()
        if BOOTSTRAP_TOKEN_STATE_FILE.exists():
            BOOTSTRAP_TOKEN_STATE_FILE.unlink()

    @classmethod
    def tearDownClass(cls):
        if PENDING_DEVICES_FILE.exists():
            PENDING_DEVICES_FILE.unlink()
        if BOOTSTRAP_TOKEN_STATE_FILE.exists():
            BOOTSTRAP_TOKEN_STATE_FILE.unlink()

    def _admin_auth_headers(self):
        auth_string = base64.b64encode(b'admin:test-magic-password').decode('utf-8')
        return {'Authorization': f'Basic {auth_string}'}

    def _request_device(self, machine_id):
        response = self.client.post('/api/provision/request', json={'machine_id': machine_id})
        self.assertEqual(response.status_code, 200)
        secret = str(response.json.get('provision_secret') or '').strip()
        self.assertTrue(secret, 'Provisioning secret should be returned on request')
        return secret

    def _approve_device(self, machine_id):
        devices = _load_pending_devices()
        self.assertIn(machine_id, devices)
        token = devices[machine_id].get('token')
        self.assertTrue(token)

        magic_response = self.client.get(
            f'/admin/devices/quick-approve?machine_id={machine_id}&token={token}',
            headers=self._admin_auth_headers(),
        )
        self.assertEqual(magic_response.status_code, 200)

    def test_status_requires_provision_secret(self):
        machine_id = 'TEST-EDGE-SECRET-001'
        provision_secret = self._request_device(machine_id)

        missing_secret = self.client.get(f'/api/provision/status?machine_id={machine_id}')
        self.assertEqual(missing_secret.status_code, 401)

        wrong_secret = self.client.get(
            f'/api/provision/status?machine_id={machine_id}&provision_secret=wrong-secret'
        )
        self.assertEqual(wrong_secret.status_code, 401)

        valid_secret = self.client.get(
            f'/api/provision/status?machine_id={machine_id}&provision_secret={provision_secret}'
        )
        self.assertEqual(valid_secret.status_code, 200)
        self.assertEqual(valid_secret.json.get('status'), 'pending')

    def test_bootstrap_exchange_flow_is_one_time(self):
        machine_id = 'TEST-EDGE-BOOTSTRAP-001'
        provision_secret = self._request_device(machine_id)
        self._approve_device(machine_id)

        status_response = self.client.get(
            f'/api/provision/status?machine_id={machine_id}&provision_secret={provision_secret}'
        )
        self.assertEqual(status_response.status_code, 200)
        payload = status_response.json or {}

        # Requirement 1: status must not directly return credentials anymore.
        self.assertNotIn('credentials', payload)
        bootstrap_token = payload.get('bootstrap_token')
        self.assertTrue(bootstrap_token)

        invalid_exchange = self.client.post(
            '/api/provision/bootstrap-exchange',
            json={
                'machine_id': machine_id,
                'provision_secret': provision_secret,
                'bootstrap_token': 'invalid',
            },
        )
        self.assertEqual(invalid_exchange.status_code, 403)

        valid_exchange = self.client.post(
            '/api/provision/bootstrap-exchange',
            json={
                'machine_id': machine_id,
                'provision_secret': provision_secret,
                'bootstrap_token': bootstrap_token,
            },
        )
        self.assertEqual(valid_exchange.status_code, 200)
        credentials = (valid_exchange.json or {}).get('credentials', {})
        self.assertTrue(str(credentials.get('SUPABASE_DB_URL') or '').startswith('postgres'))
        self.assertTrue(str(credentials.get('SUPABASE_SERVICE_ROLE_KEY') or ''))

        replay_exchange = self.client.post(
            '/api/provision/bootstrap-exchange',
            json={
                'machine_id': machine_id,
                'provision_secret': provision_secret,
                'bootstrap_token': bootstrap_token,
            },
        )
        self.assertEqual(replay_exchange.status_code, 403)

    def test_installer_download_is_token_gated_and_one_time(self):
        machine_id = 'TEST-EDGE-INSTALLER-001'
        provision_secret = self._request_device(machine_id)
        self._approve_device(machine_id)

        direct_static = self.client.get('/static/LUNA_LocalInstaller.bat')
        self.assertEqual(direct_static.status_code, 403)
        direct_static.close()

        missing_token = self.client.get('/api/bootstrap/installer')
        self.assertEqual(missing_token.status_code, 401)
        missing_token.close()

        invalid_token = self.client.get('/api/bootstrap/installer?token=invalid')
        self.assertEqual(invalid_token.status_code, 403)
        invalid_token.close()

        status_response = self.client.get(
            f'/api/provision/status?machine_id={machine_id}&provision_secret={provision_secret}'
        )
        self.assertEqual(status_response.status_code, 200)
        installer_token = (status_response.json or {}).get('installer_token')
        self.assertTrue(installer_token)

        installer_download = self.client.get(f'/api/bootstrap/installer?token={installer_token}')
        self.assertEqual(installer_download.status_code, 200)
        self.assertIn(b'ZERO-TOUCH LOCAL INSTALLER', installer_download.data)
        installer_download.close()

        installer_replay = self.client.get(f'/api/bootstrap/installer?token={installer_token}')
        self.assertEqual(installer_replay.status_code, 403)
        installer_replay.close()


if __name__ == '__main__':
    unittest.main()