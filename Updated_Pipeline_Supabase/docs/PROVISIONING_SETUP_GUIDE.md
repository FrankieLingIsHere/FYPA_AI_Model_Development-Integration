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
- `SMTP_TIMEOUT_SECONDS` (default 8 seconds)
- `SMTP_FORCE_IPV4` (default true; useful on hosted environments with flaky IPv6 egress)
- `SMTP_PASSWORD_STRIP_SPACES` (default true; useful for Gmail app-password formatting)
- `NOTIFICATION_ASYNC` (default true)
- `NOTIFICATION_WEBHOOK_URL`

## 2) Local Edge Preparation

1. Move the installer/startup package to the target edge machine.
2. Set the cloud URL in your local launcher/provisioning script to the deployed backend URL.
3. Run provisioning from the edge machine.

No Supabase credentials are embedded in the installer or distributed in cleartext at this stage.

## 3) Secure Provisioning Flow

The backend now enforces this sequence:

1. User requests Local Mode from UI (`Run Local Mode Checkup`).
2. Local backend auto-triggers edge provisioning with `POST /api/provision/request` using persistent local `machine_id`.
3. Backend stores pending request and returns a one-time `provision_secret` to that edge client.
4. Admin approves device from admin routes (`/admin/devices` or quick-approve link).
5. Local backend polls `GET /api/provision/status` with both:
  - `machine_id`
  - `provision_secret`
6. After approval, status endpoint returns short-lived one-time tokens:
  - `bootstrap_token` for credential exchange
  - `installer_token` for installer download
7. Local backend exchanges credentials through `POST /api/provision/bootstrap-exchange` with:
  - `machine_id`
  - `provision_secret`
  - `bootstrap_token`
8. Local backend writes received Supabase credentials into local `.env` and applies them to runtime.

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
