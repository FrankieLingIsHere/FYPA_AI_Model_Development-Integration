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
- `PROVISION_PENDING_REREQUEST_NOTIFY_COOLDOWN_SECONDS` (default 300; throttles repeated pending-request admin alerts)
- `LUNA_STATE_DIR` (recommended local default: `C:\LUNA_System\LUNA_LocalState`)

### Optional notifications
- `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `ADMIN_EMAIL`
- `SMTP_TIMEOUT_SECONDS` (default 8 seconds)
- `SMTP_FORCE_IPV4` (default true; useful on hosted environments with flaky IPv6 egress)
- `SMTP_PASSWORD_STRIP_SPACES` (default true; useful for Gmail app-password formatting)
- `NOTIFICATION_ASYNC` (default true)
- `RESEND_API_KEY`, `RESEND_FROM_EMAIL` (optional HTTPS email fallback)
- `RESEND_API_BASE_URL` (optional, default `https://api.resend.com`)
- `NOTIFICATION_WEBHOOK_URL`

## 2) Local Edge Preparation

1. Move the installer/startup package to the target edge machine.
2. Set the cloud URL in your local launcher/provisioning script to the deployed backend URL.
3. Run provisioning from the edge machine.

Installer delivery is token-gated. For approved devices, the one-time downloaded installer can include cloud URL and server-side Supabase credentials when those credentials are configured on the cloud backend.

If credentials are not embedded (for example, cloud credentials not configured yet), runtime bootstrap exchange remains the fallback path.

## 3) Secure Provisioning Flow

The backend now enforces this sequence:

1. User requests Local Mode from UI (`Run Local Mode Checkup`).
2. Provision request bootstrap can start from either path:
  - Local backend path: local runtime calls `POST /api/provision/request` using persistent local `machine_id`.
  - Deployed-UI first-install path (no local backend yet): frontend checkup calls `POST /api/provision/request` directly and keeps returned `provision_secret` in browser-local state until installer is downloaded.
3. Backend stores pending request and returns a one-time `provision_secret` to the requesting client.
4. Admin approves device from admin routes (`/admin/devices` or quick-approve link).
5. Requesting client polls `GET /api/provision/status` with both:
  - `machine_id`
  - `provision_secret`
6. After approval, status endpoint returns short-lived one-time tokens:
  - `bootstrap_token` for credential exchange
  - `installer_token` for installer download
7. Installer download (`/api/bootstrap/installer?token=...`) can now pre-seed local `.env` with cloud URL and Supabase credentials (when cloud credentials are configured).
8. If installer did not include credentials, local backend exchanges credentials through `POST /api/provision/bootstrap-exchange` with:
  - `machine_id`
  - `provision_secret`
  - `bootstrap_token`
9. Local backend writes received Supabase credentials into local `.env` and applies them to runtime.
10. Local backend publishes periodic readiness heartbeat to cloud using `POST /api/local-mode/heartbeat` with:
  - `machine_id`
  - `provision_secret`
  - local diagnostics (`local_mode_possible`, Ollama/model readiness)

Fresh heartbeat status is exposed to deployed UI via `GET /api/reports/recovery/options` in `cloud_local_heartbeat`.
This allows deployed-app Local Mode Checkup to validate edge readiness without directly probing browser localhost.

Legacy/manual equivalent sequence remains available:

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

Status polling still does not return credentials directly.

Re-issuing a `provision_secret` for an already approved device keeps its approved/provisioned status (it does not downgrade back to pending).

For repeated requests from the same still-pending device, admin notifications are throttled by
`PROVISION_PENDING_REREQUEST_NOTIFY_COOLDOWN_SECONDS` to reduce alert spam while still allowing reminder notifications.

## 4) Installer Delivery Security

Installer access is token-gated:

- Direct static path `/static/LUNA_LocalInstaller.bat` is blocked.
- Use `/api/bootstrap/installer/request` to issue a one-time installer token.
  - For approved/provisioned devices, `machine_id` alone is sufficient for reissuing a fresh installer link (recovery path for deleted/expired downloads).
  - `provision_secret` is still accepted and validated when provided.
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
- Heartbeat endpoint rejects missing/invalid `provision_secret`.
- Recovery options include `cloud_local_heartbeat` with freshness/ready status for deployed checkup.

If these checks pass, the secure provisioning flow is operating correctly.

## 6) Operator Q&A (Final Clarifications)

### Q1: Before admin grants access, what user-system interaction should happen, and how do users know they are approved?

Expected interaction sequence:

1. End user clicks `Run Local Mode Checkup`.
2. System auto-submits provisioning request (`/api/provision/request`) and stores machine identity.
3. UI shows waiting state: request submitted, admin approval pending, machine ID, and admin portal hint.
4. UI continues background polling silently (no repeated manual actions required).
5. Once admin approves, UI auto-switches to success state and confirms credentials are active locally.

How users know approval happened:

- Provider status text changes to success:
  - `Admin approval completed. Supabase credentials are now configured locally.`
- Local checkup status line changes to provisioned state:
  - `Local mode is approved and provisioned. Cloud credentials are active on this backend.`
- A success notification appears once when provisioning completes.

If rejected:

- UI shows explicit rejection state and instructs user to contact admin and rerun checkup.

### Q2: What value should be filled for each variable, and when can we find it?

Use this table for cloud deployment and local edge bootstrap.

| Variable | Example value format | Where to get it | When available |
|---|---|---|---|
| `ADMIN_PASSWORD` | long random secret (e.g. 32+ chars) | You generate it | Before first cloud deploy |
| `BOOTSTRAP_TOKEN_SECRET` | long random secret (e.g. 64+ chars) | You generate it | Before first cloud deploy |
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` | Supabase Dashboard -> Project Settings -> API | After project creation |
| `SUPABASE_SERVICE_ROLE_KEY` | `eyJ...` (service role key) | Supabase Dashboard -> Project Settings -> API Keys | After project creation |
| `SUPABASE_DB_URL` | `postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres` | Supabase Dashboard -> Project Settings -> Database / Connection string | After DB password is set |
| `CLOUD_URL` | `https://<your-railway-domain>.up.railway.app` | Railway deployment URL | After first successful deploy |
| `NOTIFICATION_WEBHOOK_URL` (optional) | `https://discord.com/api/webhooks/...` or Slack webhook URL | Messaging platform webhook settings | Any time (before notifications) |
| `SMTP_SERVER` (optional) | e.g. `smtp.office365.com` | Email provider SMTP settings | Any time (before email notifications) |
| `SMTP_PORT` (optional) | usually `587` | Email provider SMTP settings | Any time |
| `SMTP_USERNAME` (optional) | sender account email/username | Email provider account | Any time |
| `SMTP_PASSWORD` (optional) | app password / SMTP credential | Email provider security/app-password page | Any time |
| `ADMIN_EMAIL` (optional) | approver mailbox (e.g. `admin@company.com`) | Your chosen destination inbox | Any time |
| `SMTP_TIMEOUT_SECONDS` (optional) | integer seconds (e.g. `8`) | Your backend env setting | Any time |
| `SMTP_FORCE_IPV4` (optional) | `true` or `false` | Your backend env setting | Any time |
| `SMTP_PASSWORD_STRIP_SPACES` (optional) | `true` or `false` | Your backend env setting | Any time |
| `NOTIFICATION_ASYNC` (optional) | `true` or `false` | Your backend env setting | Any time |
| `RESEND_API_KEY` (optional) | API key string from Resend dashboard | Resend account API keys | Any time |
| `RESEND_FROM_EMAIL` (optional) | sender identity (e.g. `LUNA Alerts <alerts@your-domain.com>`) | Verified sender/domain in Resend | Any time |
| `RESEND_API_BASE_URL` (optional) | default `https://api.resend.com` | Backend env setting | Any time |

Recommended secret generation:

- Generate `ADMIN_PASSWORD` and `BOOTSTRAP_TOKEN_SECRET` locally using a secure generator, then store them in Railway variables.
- Do not reuse short, human-memorable passwords for these two values.

### Q3: Is token exchange automatic, and are credentials auto-integrated into local backend?

Yes.

After the user triggers checkup once, the rest can run silently:

1. Local backend keeps polling for approval status.
2. After approval, cloud returns short-lived bootstrap token.
3. Local backend automatically calls `/api/provision/bootstrap-exchange`.
4. Returned Supabase credentials are auto-written into local `.env`.
5. Runtime environment is updated and pipeline components are reinitialized.

No manual credential copy-paste is required in normal flow.

User experience rule:

- End users should keep using the same launcher BAT/desktop shortcut created by installer.
- If LUNA is already installed, clicking that same BAT now performs a lightweight source refresh from the installer snapshot URL and then launches the app.
- Launcher logic updates are also applied automatically from the refreshed installer template, so installer behavior can evolve without full reinstall.
- Users do not need to manually switch to running `start.bat` themselves.
- Full reinstall is no longer required for normal updates; existing `venv`, `.env`, and local runtime data are preserved.
- Reinstall/refresh remains optional for recovery scenarios.

### Q4: If I received the local installer link, does that mean this machine is already provisioned?

No.

Receiving installer link means only installer delivery was authorized via a one-time installer token. It does not mean this machine has already completed credential provisioning.

Provisioning is completed only after:

1. Device approval (`approved`/`provisioned` state) and
2. Successful one-time bootstrap exchange (`/api/provision/bootstrap-exchange`) that returns Supabase credentials.

Credentials are never embedded in the installer payload itself.

If local source files are refreshed/reinstalled, keep `LUNA_STATE_DIR` on a stable path so `machine_id` and provisioning state persist across updates.

For full security control inventory and leakage-prevention controls, see:

- `docs/SECURITY_FRAMEWORKS_CREDENTIAL_PROTECTION_2026-04-16.md`
