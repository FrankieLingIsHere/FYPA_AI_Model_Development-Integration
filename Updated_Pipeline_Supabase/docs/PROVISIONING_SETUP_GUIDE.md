# Zero-Touch Edge Node Provisioning - Setup Guide

This guide documents the current secure provisioning flow, including per-device challenge binding and one-time bootstrap token exchange.

## 1) Cloud Dashboard Setup

Configure these environment variables on the cloud backend.

### Mandatory security variables
- `ADMIN_PASSWORD`: Protects admin approval routes.
- `BOOTSTRAP_TOKEN_SECRET`: HMAC signing secret for bootstrap and installer tokens.

### Mandatory provisioning credentials
- `SUPABASE_DB_URL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

### Optional hardening tuning
- `PROVISION_EXCHANGE_TOKEN_TTL_SECONDS` (default 300)
- `INSTALLER_DOWNLOAD_TOKEN_TTL_SECONDS` (default 600)
- `BOOTSTRAP_JTI_RETENTION_SECONDS` (default 86400)

### Optional notifications
- `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `ADMIN_EMAIL`
- `NOTIFICATION_WEBHOOK_URL`

## 2) Local Edge Preparation

1. Move the installer/startup package to the target edge machine.
2. Set the cloud URL in your local launcher/provisioning script to the deployed backend URL.
3. Run provisioning from the edge machine.

No Supabase credentials are embedded in the installer or distributed in cleartext at this stage.

## 3) Secure Provisioning Flow

The backend now enforces this sequence:

1. Edge calls `POST /api/provision/request` with `machine_id`.
2. Backend stores pending request and returns a one-time `provision_secret` to that edge client.
3. Admin approves device from admin routes (`/admin/devices` or quick-approve link).
4. Edge polls `GET /api/provision/status` with both:
  - `machine_id`
  - `provision_secret`
5. After approval, status endpoint returns short-lived one-time tokens:
  - `bootstrap_token` for credential exchange
  - `installer_token` for installer download
6. Edge exchanges credentials through `POST /api/provision/bootstrap-exchange` with:
  - `machine_id`
  - `provision_secret`
  - `bootstrap_token`

Credentials are returned only by the bootstrap-exchange endpoint, not by status polling.

## 4) Installer Delivery Security

Installer access is token-gated:

- Direct static path `/static/LUNA_LocalInstaller.bat` is blocked.
- Use `/api/bootstrap/installer/request` to issue a one-time installer token.
- Download via `/api/bootstrap/installer?token=...`.
- Replay of the same token is rejected.

## 5) Validation Expectations

The provisioning action tests should cover:

- Missing or wrong `provision_secret` rejected on status.
- Status does not directly include credentials.
- Invalid bootstrap exchange token rejected.
- Valid bootstrap exchange succeeds once.
- Replay bootstrap exchange rejected.
- Installer endpoint requires valid token and rejects replay.

If these checks pass, the secure provisioning flow is operating correctly.
