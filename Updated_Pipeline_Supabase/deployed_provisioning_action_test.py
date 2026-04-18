import os
import sys
import unittest
import base64
import json
import re
from unittest.mock import patch, Mock

# Ensure we can import luna_app
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Test environment setup
os.environ['FLASK_DEBUG'] = 'false'
os.environ['SERVE_FRONTEND'] = 'false'
os.environ['ADMIN_PASSWORD'] = 'test-magic-password'
os.environ['BOOTSTRAP_TOKEN_SECRET'] = 'test-bootstrap-secret'
os.environ['SUPABASE_DB_URL'] = 'postgres://test:test@localhost:5432/test'
os.environ['SUPABASE_URL'] = 'https://projtest123.supabase.co'
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = 'service-role-test-key'

from luna_app import (
    app,
    _load_pending_devices,
    _save_pending_devices,
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

    def _assert_no_cache_headers(self, response):
        self.assertEqual(
            response.headers.get('Cache-Control'),
            'no-store, no-cache, must-revalidate, max-age=0',
        )
        self.assertEqual(response.headers.get('Pragma'), 'no-cache')
        self.assertEqual(response.headers.get('Expires'), '0')

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

    def test_deployed_first_install_bootstrap_sequence(self):
        """Regression: deployed UI can bootstrap approval flow before any local backend exists."""
        machine_id = 'WEB-FIRST-INSTALL-001'

        # Step 1: Deployed client submits initial provisioning request.
        request_response = self.client.post('/api/provision/request', json={'machine_id': machine_id})
        self.assertEqual(request_response.status_code, 200)
        request_payload = request_response.json or {}
        provision_secret = str(request_payload.get('provision_secret') or '').strip()
        self.assertTrue(provision_secret)
        self.assertEqual(request_payload.get('device_status'), 'pending')

        # Step 2: Deployed client polls status using header-based secret (not query string).
        pending_status = self.client.get(
            f'/api/provision/status?machine_id={machine_id}',
            headers={'X-Provision-Secret': provision_secret},
        )
        self.assertEqual(pending_status.status_code, 200)
        self.assertEqual((pending_status.json or {}).get('status'), 'pending')

        # Step 3: Installer access must still be denied before admin approval.
        pending_installer = self.client.get(
            f'/api/bootstrap/installer/request?machine_id={machine_id}',
            follow_redirects=False,
        )
        self.assertEqual(pending_installer.status_code, 403)
        self._assert_no_cache_headers(pending_installer)
        pending_installer.close()

        # Step 4: Admin approves from dashboard.
        self._approve_device(machine_id)

        # Step 5: Same deployed client polls again and receives approved + bootstrap/installer tokens.
        approved_status = self.client.get(
            f'/api/provision/status?machine_id={machine_id}',
            headers={'X-Provision-Secret': provision_secret},
        )
        self.assertEqual(approved_status.status_code, 200)
        approved_payload = approved_status.json or {}
        self.assertEqual(approved_payload.get('status'), 'approved')
        self.assertTrue(str(approved_payload.get('bootstrap_token') or '').strip())
        self.assertTrue(str(approved_payload.get('installer_token') or '').strip())

        # Step 6: Installer issuance can now be done by machine_id only.
        installer_redirect = self.client.get(
            f'/api/bootstrap/installer/request?machine_id={machine_id}',
            follow_redirects=False,
        )
        self.assertIn(installer_redirect.status_code, (301, 302, 303, 307, 308))
        self._assert_no_cache_headers(installer_redirect)
        location = str(installer_redirect.headers.get('Location') or '')
        self.assertIn('/api/bootstrap/installer?token=', location)
        installer_redirect.close()

    def test_re_request_for_approved_device_preserves_approval_status(self):
        machine_id = 'TEST-EDGE-REISSUE-001'
        first_secret = self._request_device(machine_id)
        self._approve_device(machine_id)

        reissue = self.client.post('/api/provision/request', json={'machine_id': machine_id})
        self.assertEqual(reissue.status_code, 200)
        reissue_payload = reissue.json or {}
        self.assertEqual(reissue_payload.get('status'), 'stored')
        self.assertEqual(reissue_payload.get('device_status'), 'approved')

        second_secret = str(reissue_payload.get('provision_secret') or '').strip()
        self.assertTrue(second_secret)
        self.assertNotEqual(first_secret, second_secret)

        old_secret_status = self.client.get(
            f'/api/provision/status?machine_id={machine_id}&provision_secret={first_secret}'
        )
        self.assertEqual(old_secret_status.status_code, 401)

        new_secret_status = self.client.get(
            f'/api/provision/status?machine_id={machine_id}&provision_secret={second_secret}'
        )
        self.assertEqual(new_secret_status.status_code, 200)
        payload = new_secret_status.json or {}
        self.assertEqual(payload.get('status'), 'approved')
        self.assertTrue(payload.get('bootstrap_exchange_ready'))
        self.assertTrue(str(payload.get('bootstrap_token') or '').strip())

    @patch('luna_app.notify_admin')
    def test_re_request_pending_device_respects_notification_cooldown(self, mock_notify_admin):
        machine_id = 'TEST-EDGE-PENDING-COOLDOWN-001'
        _ = self._request_device(machine_id)
        mock_notify_admin.reset_mock()

        with patch('luna_app.PENDING_REREQUEST_NOTIFY_COOLDOWN_SECONDS', 3600):
            reissue = self.client.post('/api/provision/request', json={'machine_id': machine_id})

        self.assertEqual(reissue.status_code, 200)
        payload = reissue.json or {}
        self.assertEqual(payload.get('status'), 'stored')
        self.assertEqual(payload.get('device_status'), 'pending')
        self.assertFalse(payload.get('notification_dispatched'))
        self.assertEqual(payload.get('notification_reason'), 'pending_rerequest_cooldown')
        mock_notify_admin.assert_not_called()

    @patch('luna_app.notify_admin')
    def test_re_request_pending_device_notifies_after_cooldown(self, mock_notify_admin):
        machine_id = 'TEST-EDGE-PENDING-COOLDOWN-002'
        _ = self._request_device(machine_id)
        mock_notify_admin.reset_mock()

        devices = _load_pending_devices()
        self.assertIn(machine_id, devices)
        devices[machine_id]['requested_at'] = '2020-01-01T00:00:00+00:00'
        _save_pending_devices(devices)

        with patch('luna_app.PENDING_REREQUEST_NOTIFY_COOLDOWN_SECONDS', 60):
            reissue = self.client.post('/api/provision/request', json={'machine_id': machine_id})

        self.assertEqual(reissue.status_code, 200)
        payload = reissue.json or {}
        self.assertEqual(payload.get('status'), 'stored')
        self.assertEqual(payload.get('device_status'), 'pending')
        self.assertTrue(payload.get('notification_dispatched'))
        self.assertEqual(payload.get('notification_reason'), 'pending_rerequest_notified')
        mock_notify_admin.assert_called_once()

    def test_approved_status_requires_server_provisioning_credentials(self):
        machine_id = 'TEST-EDGE-CREDS-REQUIRED-001'
        provision_secret = self._request_device(machine_id)
        self._approve_device(machine_id)

        with patch.dict(os.environ, {
            'SUPABASE_DB_URL': '',
            'SUPABASE_URL': '',
            'SUPABASE_SERVICE_ROLE_KEY': '',
        }, clear=False):
            status_response = self.client.get(
                f'/api/provision/status?machine_id={machine_id}&provision_secret={provision_secret}'
            )

        self.assertEqual(status_response.status_code, 503)
        payload = status_response.json or {}
        self.assertEqual(payload.get('status'), 'approved')
        self.assertFalse(payload.get('bootstrap_exchange_ready'))
        self.assertNotIn('bootstrap_token', payload)
        self.assertNotIn('installer_token', payload)
        self.assertEqual(
            set(payload.get('missing_env_keys') or []),
            {'SUPABASE_DB_URL', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY'}
        )

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
        self.assertTrue(payload.get('bootstrap_exchange_ready'))
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

        request_machine_only = self.client.get(
            f'/api/bootstrap/installer/request?machine_id={machine_id}',
            follow_redirects=False,
        )
        self.assertIn(request_machine_only.status_code, (301, 302, 303, 307, 308))
        self._assert_no_cache_headers(request_machine_only)
        machine_only_location = str(request_machine_only.headers.get('Location') or '')
        self.assertIn('/api/bootstrap/installer?token=', machine_only_location)
        request_machine_only.close()

        request_unauth = self.client.get('/api/bootstrap/installer/request')
        self.assertEqual(request_unauth.status_code, 401)
        self._assert_no_cache_headers(request_unauth)
        request_unauth.close()

        request_auth = self.client.get(
            '/api/bootstrap/installer/request',
            headers=self._admin_auth_headers(),
            follow_redirects=False,
        )
        self.assertIn(request_auth.status_code, (301, 302, 303, 307, 308))
        self._assert_no_cache_headers(request_auth)
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
        rendered_installer = installer_download.data.decode('utf-8', errors='ignore')
        # Assignment placeholders must be replaced in rendered downloads.
        self.assertNotIn('set "LUNA_REPO_ZIP_URL=__LUNA_REPO_ZIP_URL__"', rendered_installer)
        self.assertNotIn('set "LUNA_SOURCE_ROOT=__LUNA_SOURCE_ROOT__"', rendered_installer)
        self.assertNotIn('set "LUNA_CLOUD_URL=__LUNA_CLOUD_URL__"', rendered_installer)
        self.assertNotIn('set "LUNA_INSTALLER_VERSION=__LUNA_INSTALLER_VERSION__"', rendered_installer)
        self.assertNotIn('set "LUNA_MACHINE_ID=__LUNA_MACHINE_ID__"', rendered_installer)
        self.assertNotIn('set "LUNA_SUPABASE_URL=__LUNA_SUPABASE_URL__"', rendered_installer)
        self.assertNotIn('set "LUNA_SUPABASE_DB_URL=__LUNA_SUPABASE_DB_URL__"', rendered_installer)
        self.assertNotIn('set "LUNA_SUPABASE_SERVICE_ROLE_KEY=__LUNA_SUPABASE_SERVICE_ROLE_KEY__"', rendered_installer)

        # Internal guard checks and self-update token maps must preserve placeholders
        # so launcher self-refresh can re-render from template safely.
        self.assertIn('if /I "!LUNA_CLOUD_URL!"=="__LUNA_CLOUD_URL__"', rendered_installer)
        self.assertIn("'__LUNA_REPO_ZIP_URL__'='LUNA_REPO_ZIP_URL'", rendered_installer)
        self.assertGreaterEqual(
            rendered_installer.count("'__LUNA_REPO_ZIP_URL__'='LUNA_REPO_ZIP_URL'"),
            2,
        )

        # Ensure critical launcher labels are present in rendered payload.
        self.assertRegex(rendered_installer, r'(?im)^:safe_refresh_local_launcher\s*$')
        self.assertRegex(rendered_installer, r'(?im)^:refresh_local_launcher_from_template\s*$')
        self.assertRegex(rendered_installer, r'(?im)^:repair_startup_batch_label_mismatch\s*$')
        self.assertIn('set "LUNA_REPO_ZIP_URL=', rendered_installer)
        self.assertIn('set "LUNA_SOURCE_ROOT=', rendered_installer)
        self.assertIn('set "LUNA_CLOUD_URL=', rendered_installer)
        self.assertIn('set "LUNA_SUPABASE_URL=https://projtest123.supabase.co"', rendered_installer)
        self.assertIn('set "LUNA_SUPABASE_DB_URL=postgres://test:test@localhost:5432/test"', rendered_installer)
        self.assertIn('set "LUNA_SUPABASE_SERVICE_ROLE_KEY=service-role-test-key"', rendered_installer)
        self.assertTrue(str(installer_download.headers.get('X-Luna-Installer-Version') or '').strip())
        self.assertEqual(
            installer_download.headers.get('Cache-Control'),
            'no-store, no-cache, must-revalidate, max-age=0',
        )
        installer_download.close()

        installer_replay = self.client.get(f'/api/bootstrap/installer?token={installer_token}')
        self.assertEqual(installer_replay.status_code, 403)
        installer_replay.close()

    def test_batch_templates_have_required_label_targets(self):
        script_dir = os.path.abspath(os.path.dirname(__file__))
        start_bat_path = os.path.join(script_dir, 'start.bat')
        installer_bat_path = os.path.join(script_dir, 'frontend', 'static', 'LUNA_LocalInstaller.bat')

        with open(start_bat_path, 'r', encoding='utf-8') as f:
            start_bat = f.read()

        with open(installer_bat_path, 'r', encoding='utf-8') as f:
            installer_bat = f.read()

        self.assertIn('call :safe_start_ollama_and_wait_ready 30', start_bat)
        self.assertRegex(start_bat, r'(?im)^:safe_start_ollama_and_wait_ready\s*$')
        self.assertRegex(start_bat, r'(?im)^:start_ollama_and_wait_ready\s*$')
        self.assertRegex(start_bat, r'(?im)^:spawn_ollama_server\s*$')
        self.assertRegex(start_bat, r'(?im)^:is_ollama_ready\s*$')

        if 'call :start_ollama_and_wait_ready' in start_bat:
            self.assertRegex(start_bat, r'(?im)^:start_ollama_and_wait_ready\s*$')

        self.assertIn('call :safe_refresh_local_launcher', installer_bat)
        self.assertIn('call :repair_startup_batch_label_mismatch', installer_bat)
        self.assertRegex(installer_bat, r'(?im)^:safe_refresh_local_launcher\s*$')
        self.assertRegex(installer_bat, r'(?im)^:refresh_local_launcher_from_template\s*$')
        self.assertRegex(installer_bat, r'(?im)^:repair_startup_batch_label_mismatch\s*$')

        token_map_key = "'__LUNA_REPO_ZIP_URL__'='LUNA_REPO_ZIP_URL'"
        self.assertGreaterEqual(installer_bat.count(token_map_key), 2)
        self.assertGreaterEqual(installer_bat.count('$lineMap = [ordered]@{}'), 2)

    def test_machine_only_installer_request_rejects_pending_device(self):
        machine_id = 'TEST-EDGE-INSTALLER-PENDING-001'
        _ = self._request_device(machine_id)

        pending_resp = self.client.get(
            f'/api/bootstrap/installer/request?machine_id={machine_id}',
            follow_redirects=False,
        )
        self.assertEqual(pending_resp.status_code, 403)
        self._assert_no_cache_headers(pending_resp)
        pending_resp.close()

    def test_local_mode_status_recovers_canonical_machine_id_from_saved_secret(self):
        canonical_machine_id = 'Web-897DE863'
        drifted_machine_id = 'Edge-405D88DCC9E4'
        provision_secret = self._request_device(canonical_machine_id)

        LOCAL_MODE_MACHINE_ID_FILE.write_text(drifted_machine_id, encoding='utf-8')
        LOCAL_MODE_PROVISION_STATE_FILE.write_text(
            json.dumps({
                'machine_id': drifted_machine_id,
                'provision_secret': provision_secret,
                'status': 'pending_approval',
                'requested_at': '2026-04-16T00:00:00+00:00',
                'updated_at': '2026-04-16T00:00:00+00:00',
            }),
            encoding='utf-8',
        )

        response = self.client.get('/api/local-mode/provisioning/status')
        self.assertEqual(response.status_code, 200)
        payload = response.json or {}
        self.assertEqual(payload.get('machine_id'), canonical_machine_id)

        persisted = json.loads(LOCAL_MODE_PROVISION_STATE_FILE.read_text(encoding='utf-8'))
        self.assertEqual(str(persisted.get('machine_id') or ''), canonical_machine_id)
        self.assertEqual(LOCAL_MODE_MACHINE_ID_FILE.read_text(encoding='utf-8').strip(), canonical_machine_id)

    def test_installer_request_recovers_from_local_state_machine_id_drift(self):
        canonical_machine_id = 'Web-897DE863'
        drifted_machine_id = 'Edge-405D88DCC9E4'
        provision_secret = self._request_device(canonical_machine_id)
        self._approve_device(canonical_machine_id)

        LOCAL_MODE_MACHINE_ID_FILE.write_text(drifted_machine_id, encoding='utf-8')
        LOCAL_MODE_PROVISION_STATE_FILE.write_text(
            json.dumps({
                'machine_id': drifted_machine_id,
                'provision_secret': provision_secret,
                'status': 'approved',
                'requested_at': '2026-04-16T00:00:00+00:00',
                'updated_at': '2026-04-16T00:00:00+00:00',
            }),
            encoding='utf-8',
        )

        installer_redirect = self.client.get(
            f'/api/bootstrap/installer/request?machine_id={drifted_machine_id}',
            follow_redirects=False,
        )
        self.assertIn(installer_redirect.status_code, (301, 302, 303, 307, 308))
        location = str(installer_redirect.headers.get('Location') or '')
        self.assertIn('/api/bootstrap/installer?token=', location)
        installer_redirect.close()

        persisted = json.loads(LOCAL_MODE_PROVISION_STATE_FILE.read_text(encoding='utf-8'))
        self.assertEqual(str(persisted.get('machine_id') or ''), canonical_machine_id)
        self.assertEqual(LOCAL_MODE_MACHINE_ID_FILE.read_text(encoding='utf-8').strip(), canonical_machine_id)

    def test_installer_request_can_resolve_machine_id_from_provision_secret(self):
        canonical_machine_id = 'Web-897DE863'
        wrong_machine_id = 'Edge-405D88DCC9E4'
        provision_secret = self._request_device(canonical_machine_id)
        self._approve_device(canonical_machine_id)

        installer_redirect = self.client.get(
            f'/api/bootstrap/installer/request?machine_id={wrong_machine_id}&provision_secret={provision_secret}',
            follow_redirects=False,
        )
        self.assertIn(installer_redirect.status_code, (301, 302, 303, 307, 308))
        self._assert_no_cache_headers(installer_redirect)
        location = str(installer_redirect.headers.get('Location') or '')
        self.assertIn('/api/bootstrap/installer?token=', location)
        installer_redirect.close()

    def test_installer_request_secret_overrides_pending_machine_id_collision(self):
        approved_machine_id = 'WEB-INSTALLER-APPROVED-SECRET-001'
        pending_machine_id = 'WEB-INSTALLER-PENDING-SECRET-001'

        approved_secret = self._request_device(approved_machine_id)
        _ = self._request_device(pending_machine_id)
        self._approve_device(approved_machine_id)

        installer_redirect = self.client.get(
            f'/api/bootstrap/installer/request?machine_id={pending_machine_id}&provision_secret={approved_secret}',
            follow_redirects=False,
        )
        self.assertIn(installer_redirect.status_code, (301, 302, 303, 307, 308))
        self._assert_no_cache_headers(installer_redirect)
        location = str(installer_redirect.headers.get('Location') or '')
        self.assertIn('/api/bootstrap/installer?token=', location)
        installer_redirect.close()

        devices = _load_pending_devices()
        self.assertEqual(str((devices.get(pending_machine_id) or {}).get('status') or ''), 'pending')

    def test_admin_reset_all_clears_cloud_provisioning_records(self):
        self._request_device('TEST-EDGE-RESET-001')
        self._request_device('TEST-EDGE-RESET-002')
        BOOTSTRAP_TOKEN_STATE_FILE.write_text(
            json.dumps({'used_jti': {'jti-1': '2026-04-16T00:00:00+00:00'}}),
            encoding='utf-8',
        )

        response = self.client.post(
            '/admin/devices',
            data={'action': 'reset_all'},
            headers=self._admin_auth_headers(),
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        location = str(response.headers.get('Location') or '')
        self.assertIn('/admin/devices?reset_all=1', location)
        self.assertIn('cleared_devices=2', location)
        self.assertIn('cleared_tokens=1', location)

        devices_after_reset = _load_pending_devices()
        self.assertEqual(devices_after_reset, {})

        self.assertTrue(BOOTSTRAP_TOKEN_STATE_FILE.exists())
        token_state = json.loads(BOOTSTRAP_TOKEN_STATE_FILE.read_text(encoding='utf-8'))
        self.assertEqual(token_state.get('used_jti'), {})

    def test_local_auto_provision_requires_cloud_url(self):
        previous_cloud_url = os.environ.pop('CLOUD_URL', None)
        try:
            response = self.client.post('/api/local-mode/provisioning/auto', json={})
            self.assertEqual(response.status_code, 400)
            payload = response.json or {}
            self.assertEqual(payload.get('status'), 'cloud_url_missing')
            self.assertIn('CLOUD_URL', str(payload.get('error') or ''))

            # Browser-opened endpoint uses GET; ensure it does not fail with 405.
            get_response = self.client.get('/api/local-mode/provisioning/auto')
            self.assertEqual(get_response.status_code, 400)
            get_payload = get_response.json or {}
            self.assertEqual(get_payload.get('status'), 'cloud_url_missing')
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

        # Provisioning request + heartbeat snapshot upload.
        self.assertEqual(mock_post.call_count, 2)
        request_url = str(mock_post.call_args_list[0].args[0])
        self.assertIn('/api/provision/request', request_url)
        heartbeat_url = str(mock_post.call_args_list[1].args[0])
        self.assertIn('/api/local-mode/heartbeat', heartbeat_url)

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

        # Provision request + bootstrap exchange + heartbeat snapshot upload.
        self.assertEqual(mock_post.call_count, 3)
        first_url = str(mock_post.call_args_list[0].args[0])
        second_url = str(mock_post.call_args_list[1].args[0])
        third_url = str(mock_post.call_args_list[2].args[0])
        self.assertIn('/api/provision/request', first_url)
        self.assertIn('/api/provision/bootstrap-exchange', second_url)
        self.assertIn('/api/local-mode/heartbeat', third_url)

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