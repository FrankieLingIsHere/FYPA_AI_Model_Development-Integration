import os
import sys
import unittest
import base64
import json
from unittest.mock import patch, Mock

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

from luna_app import (
    app,
    _load_pending_devices,
    PENDING_DEVICES_FILE,
    BOOTSTRAP_TOKEN_STATE_FILE,
    LOCAL_MODE_PROVISION_STATE_FILE,
    LOCAL_MODE_MACHINE_ID_FILE,
)


class ProvisioningActionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def setUp(self):
        if PENDING_DEVICES_FILE.exists():
            PENDING_DEVICES_FILE.unlink()
        if BOOTSTRAP_TOKEN_STATE_FILE.exists():
            BOOTSTRAP_TOKEN_STATE_FILE.unlink()
        if LOCAL_MODE_PROVISION_STATE_FILE.exists():
            LOCAL_MODE_PROVISION_STATE_FILE.unlink()
        if LOCAL_MODE_MACHINE_ID_FILE.exists():
            LOCAL_MODE_MACHINE_ID_FILE.unlink()

    @classmethod
    def tearDownClass(cls):
        if PENDING_DEVICES_FILE.exists():
            PENDING_DEVICES_FILE.unlink()
        if BOOTSTRAP_TOKEN_STATE_FILE.exists():
            BOOTSTRAP_TOKEN_STATE_FILE.unlink()
        if LOCAL_MODE_PROVISION_STATE_FILE.exists():
            LOCAL_MODE_PROVISION_STATE_FILE.unlink()
        if LOCAL_MODE_MACHINE_ID_FILE.exists():
            LOCAL_MODE_MACHINE_ID_FILE.unlink()

    def _mock_http_response(self, status_code, payload):
        response = Mock()
        response.status_code = status_code
        response.ok = 200 <= status_code < 300
        response.content = json.dumps(payload).encode('utf-8')
        response.json.return_value = payload
        return response

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

        request_unauth = self.client.get('/api/bootstrap/installer/request')
        self.assertEqual(request_unauth.status_code, 401)
        request_unauth.close()

        request_auth = self.client.get(
            '/api/bootstrap/installer/request',
            headers=self._admin_auth_headers(),
            follow_redirects=False,
        )
        self.assertIn(request_auth.status_code, (301, 302, 303, 307, 308))
        location = str(request_auth.headers.get('Location') or '')
        self.assertIn('/api/bootstrap/installer?token=', location)
        request_auth.close()

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

    def test_local_auto_provision_requires_cloud_url(self):
        previous_cloud_url = os.environ.pop('CLOUD_URL', None)
        try:
            response = self.client.post('/api/local-mode/provisioning/auto', json={})
            self.assertEqual(response.status_code, 400)
            payload = response.json or {}
            self.assertEqual(payload.get('status'), 'cloud_url_missing')
            self.assertIn('CLOUD_URL', str(payload.get('error') or ''))
        finally:
            if previous_cloud_url is not None:
                os.environ['CLOUD_URL'] = previous_cloud_url

    @patch('luna_app.requests.get')
    @patch('luna_app.requests.post')
    def test_local_auto_provision_pending_approval(self, mock_post, mock_get):
        os.environ['CLOUD_URL'] = 'https://cloud.example.test'

        mock_post.return_value = self._mock_http_response(
            200,
            {'status': 'stored', 'provision_secret': 'local-secret-001'},
        )
        mock_get.return_value = self._mock_http_response(
            200,
            {'status': 'pending'},
        )

        with patch('luna_app._local_mode_has_supabase_credentials', return_value=False):
            response = self.client.post('/api/local-mode/provisioning/auto', json={})
        self.assertEqual(response.status_code, 200)

        payload = response.json or {}
        self.assertTrue(payload.get('success'))
        self.assertEqual(payload.get('status'), 'pending_approval')
        self.assertTrue(str(payload.get('machine_id') or '').strip())
        self.assertEqual(payload.get('admin_portal_url'), 'https://cloud.example.test/admin/devices')

        self.assertTrue(LOCAL_MODE_PROVISION_STATE_FILE.exists())
        persisted = json.loads(LOCAL_MODE_PROVISION_STATE_FILE.read_text(encoding='utf-8'))
        self.assertEqual(persisted.get('status'), 'pending')
        self.assertEqual(str(persisted.get('provision_secret') or ''), 'local-secret-001')

        self.assertEqual(mock_post.call_count, 1)
        request_url = str(mock_post.call_args_list[0].args[0])
        self.assertIn('/api/provision/request', request_url)

    @patch('luna_app._local_mode_apply_supabase_credentials')
    @patch('luna_app.requests.get')
    @patch('luna_app.requests.post')
    def test_local_auto_provision_approved_auto_exchanges_and_applies_credentials(
        self,
        mock_post,
        mock_get,
        mock_apply_credentials,
    ):
        os.environ['CLOUD_URL'] = 'https://cloud.example.test'

        expected_credentials = {
            'SUPABASE_DB_URL': 'postgres://auto:test@localhost:5432/test',
            'SUPABASE_URL': 'https://auto-example.supabase.co',
            'SUPABASE_SERVICE_ROLE_KEY': 'auto-service-role-key',
        }

        request_response = self._mock_http_response(
            200,
            {'status': 'stored', 'provision_secret': 'local-secret-002'},
        )
        exchange_response = self._mock_http_response(
            200,
            {'status': 'provisioned', 'credentials': expected_credentials},
        )
        mock_post.side_effect = [request_response, exchange_response]

        mock_get.return_value = self._mock_http_response(
            200,
            {'status': 'approved', 'bootstrap_token': 'bootstrap-xyz'},
        )

        mock_apply_credentials.return_value = {
            'success': True,
            'reinitialized': True,
            'reinit_error': None,
        }

        with patch('luna_app._local_mode_has_supabase_credentials', return_value=False):
            response = self.client.post('/api/local-mode/provisioning/auto', json={})
        self.assertEqual(response.status_code, 200)

        payload = response.json or {}
        self.assertTrue(payload.get('success'))
        self.assertEqual(payload.get('status'), 'provisioned')
        self.assertTrue(payload.get('provisioned'))
        self.assertTrue(payload.get('reinitialized'))
        self.assertEqual(payload.get('admin_portal_url'), 'https://cloud.example.test/admin/devices')

        self.assertEqual(mock_post.call_count, 2)
        first_url = str(mock_post.call_args_list[0].args[0])
        second_url = str(mock_post.call_args_list[1].args[0])
        self.assertIn('/api/provision/request', first_url)
        self.assertIn('/api/provision/bootstrap-exchange', second_url)

        second_payload = mock_post.call_args_list[1].kwargs.get('json') or {}
        self.assertEqual(second_payload.get('bootstrap_token'), 'bootstrap-xyz')
        self.assertTrue(str(second_payload.get('machine_id') or '').strip())

        mock_apply_credentials.assert_called_once_with(expected_credentials)

        self.assertTrue(LOCAL_MODE_PROVISION_STATE_FILE.exists())
        persisted = json.loads(LOCAL_MODE_PROVISION_STATE_FILE.read_text(encoding='utf-8'))
        self.assertEqual(persisted.get('status'), 'provisioned')
        self.assertTrue(str(persisted.get('provisioned_at') or '').strip())


if __name__ == '__main__':
    unittest.main()