# Deployment and operations

Even a "production-style" deployment of this repository runs in **simulation only**: nothing it does moves real money. These notes cover how to run the prototype safely and what a real operator would need.

## Local development vs. production

| | Local development | Shared / production-style |
|---|---|---|
| Transport | Plain HTTP on `localhost` | **HTTPS only.** Terminate TLS at a reverse proxy or load balancer in front of `web`, with TLS 1.2+ and HSTS. |
| Cookies | `COOKIE_SECURE=false` | `COOKIE_SECURE=true` (enforced when `APP_ENV=production`) |
| Secrets | `scripts/generate-dev-env.sh` writes random values to `.env` | Injected from a secrets manager or KMS. No `.env` files on disk; never committed. |
| Database | SQLite or the Compose Postgres | Managed PostgreSQL with TLS, backups, and least-privilege roles |
| Schema | `DB_AUTO_CREATE=true` for SQLite convenience | `alembic upgrade head` as a separate step (the `migrate` service) |
| Demo data | `seed` service | Disabled (the `seed` service is in the `never` profile in `docker-compose.prod.yml`) |
| API docs | `/api/docs` | Disabled |

Start a production-style deployment:

```bash
CORS_ORIGINS=https://yogii.example.com \
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

`web` listens on `127.0.0.1:8080`. Point the TLS terminator at it. Never publish the `api` or `db` ports.

## Secrets

| Secret | Purpose |
|---|---|
| `JWT_SECRET` | Signs session tokens |
| `YOGII_ENCRYPTION_KEY` | Encrypts personal data (AES-256-GCM) |
| `YOGII_LOOKUP_HMAC_KEY` | Blind indexes |
| `MOCK_PROVIDER_WEBHOOK_SECRET` | Mock rail callbacks |
| `POSTGRES_PASSWORD` | Postgres superuser; used only by the container init |
| `YOGII_MIGRATOR_PASSWORD` | Schema-owner role |
| `YOGII_APP_PASSWORD` | Least-privilege application role |

Generate each with `openssl rand -hex 32` (use hex, since values end up in connection URLs). Rotate `JWT_SECRET` to sign everyone out.

Encryption keys carry a version (`YOGII_KEY_VERSION`, stored with each ciphertext). Rotating them needs a re-encryption job, which is not included yet.

## Database roles

`infrastructure/postgres/init/01-roles.sh` runs when the data volume is first created:
- **`yogii_migrator`** owns the schema.
- **`yogii_app`** gets data access only, through default privileges.

Migration `0003` then removes `UPDATE`, `DELETE` and `TRUNCATE` on audit-type tables from `yogii_app`. On a managed database, create the same roles yourself and run migrations with the owner role.

## Backups

| Setup | Command |
|---|---|
| Compose | `docker compose exec -T db pg_dump -U postgres --format=custom yogii > backups/yogii-<date>.dump` |
| Managed PostgreSQL | Enable automated backups and point-in-time recovery, and keep a copy in a separate account or region. |
| Scripts | `python -m backend.scripts.backup` (pg_dump custom format, or a consistent SQLite copy; files are mode `600`) |

**Guidelines:**
- Back up at least daily, and before every migration.
- Encrypt backups at rest.
- Store the application encryption keys **separately** from the backups.

## Restore (and practise it)

1. Stop the API: `docker compose stop api`.
2. Restore:
   `docker compose exec -T db pg_restore -U postgres --clean --if-exists --single-transaction -d yogii < backups/<file>.dump`
   Or: `python -m backend.scripts.restore <file> --yes`.
3. Bring the schema up to date: `docker compose run --rm migrate` (or `alembic upgrade head`).
4. Start the API. Check `/api/ready`, sign in, and open a payment's detail page. This confirms decryption works with the current keys.

**Run a restore drill regularly** into a scratch environment. A backup you have never restored is not a backup.

## Audit logs

- **Database:**
  - `audit_events` records registration, login, assessment, verification, authorisation, cancellation and session revocation.
  - `security_events` records failed and locked logins, blocked payments and rejected callbacks.
  - `payment_state_transitions` records every state change.
  - `provider_callback_events` records every callback.
  - The app role can't modify any of these.
- **Stdout:** the same events are written as structured JSON lines (`AUDIT_EVENT:` / `SECURITY_EVENT:`), with secret-like keys removed. Ship container logs to a central store with its own retention and access controls.
- **Retention:** schedule `docker compose --profile ops run --rm retention` daily. It runs as the schema-owner role, because the app role can't delete audit-type data. Without Docker: `python -m backend.scripts.retention` with a `DATABASE_URL` for the owner role. See [SECURITY_AND_PRIVACY.md](SECURITY_AND_PRIVACY.md).
- **Reconciliation:** `python -m backend.scripts.reconcile YYYY-MM-DD` compares the day's payments with the rail and lists mismatches. It never changes balances.

## Monitoring

- **Liveness:** `/api/health`. **Readiness:** `/api/ready` (checks the database and the model).
- **Alert on:**
  - bursts of `login_failure` / `login_locked`;
  - `provider_callback_rejected`;
  - `payment_blocked` rates;
  - 5xx rates;
  - `ModelNotAvailableError` in the logs;
  - reconciliation mismatches.

## Incident response (outline)

1. **Detect and triage:** alerts, user reports, reconciliation mismatches. Record a timeline from the first moment.
2. **Contain.** Stop the `api` service, or put the site into maintenance at the proxy.
   - For a suspected credential leak, rotate the relevant secret. Rotating `JWT_SECRET` invalidates all sessions.
   - For a suspected callback forgery, rotate `MOCK_PROVIDER_WEBHOOK_SECRET` (with a real bank, follow their process).
3. **Preserve evidence:** snapshot the database and export `audit_events`, `security_events`, `provider_callback_events` and container logs before changing anything.
4. **Eradicate and recover:** fix the cause, restore from a known-good backup if data was altered, then re-run reconciliation.
5. **Notify.** Follow the obligations that apply to the deployment: users, and in a real deployment the sponsor bank and the relevant authorities within their required timelines. This prototype holds only fictional and demo data, but the process should be rehearsed as if it didn't.
6. **Review:** a blameless post-incident review, with action items tracked to completion.

## Before anything real

See [INTEGRATION_BOUNDARY.md](INTEGRATION_BOUNDARY.md). At minimum:
- sponsor-bank / PSP onboarding and certification;
- model validation on permitted data;
- a policy approved by the bank;
- key management in an HSM or KMS;
- MFA, shared rate limiting, a penetration test;
- a current legal and compliance review.
