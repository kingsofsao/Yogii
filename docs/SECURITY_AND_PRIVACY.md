# Security and privacy

These controls are in place for a prototype. They don't make Yogii compliant with any regulation or certify it for real payments.

## Credentials Yogii never handles

Yogii never collects, processes, logs or stores:
- a UPI PIN (or MPIN), an OTP, a CVV or card number, or a bank or net-banking password.

This is enforced in several places:
- Every request schema rejects fields with those names, at any nesting depth, with HTTP 422. The submitted value is never echoed back.
- There is no database column for any of them.
- `PaymentInitiationRequest` has no such field.
- Audit logging strips keys that look like secrets.
- The demo verification step is a checklist, not a bank authentication step.

## Authentication and sessions

- **Passwords:** Argon2id (`argon2-cffi`), rehashed on login if the parameters change. The policy is at least 10 characters with upper and lower case letters and a number.
- **Session token:** a short-lived signed JWT (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 30) in an **HttpOnly, SameSite=Strict** cookie, with `Secure` set in production. JavaScript can't read it.
- **CSRF:** double submit. The token carries a random CSRF value, and every unsafe request must send it in `X-CSRF-Token`.
- **Revocation:** "Sign out on all devices" increments `users.token_version`, which invalidates every existing token server-side.
- **Login errors are generic.** The response doesn't say whether the account exists. A dummy Argon2 check equalises timing for unknown accounts.
- **Lockout:** 5 failures per identifier within 15 minutes. There's also a per-IP limit of 10 logins per minute.
- **Rate limits:** registration 5/min/IP; assessment and authorisation 20/min/user; recipient lookup 30/min/user; callbacks 120/min/IP. nginx adds its own limits. The limiter is in-memory and per process, so a multi-instance deployment should move it to a shared store.

## Authorisation

- Every payment query is scoped to the signed-in sender. Another user's payment returns **404**, never 403, so its existence isn't revealed.
- Recipient lookup returns only a display name, UPI ID and payee type.
- Receiver aggregates, such as inflow counts and account age, are model inputs only and are never returned to the sender. Users see only the generic `RECEIVER_RISK_SIGNAL` reason.

## Data protection

- **Personal data encryption.** Name, email, phone, UPI ID and payment notes are encrypted with **AES-256-GCM**, using versioned keys.
- **Lookup without plaintext.** Lookups use **HMAC-SHA-256 blind indexes** of normalised values.
- **Hashed graph nodes and signals.** Transaction-graph nodes are truncated keyed hashes. The simulated device and location labels are stored only as keyed hashes.
- **Money.** Values are `NUMERIC(14,2)`, never floats.
- **Input validation.** Inputs are validated and normalised: UPI IDs, Indian mobile numbers, emails, names, amounts (at most 2 decimals, ₹1 to ₹1,00,000), and strict request schemas.
- **SQL.** All database access goes through the SQLAlchemy ORM or bound parameters.

## Database access

In the Compose setup:

| Role | Can | Can't |
|---|---|---|
| `yogii_migrator` | Owns the schema; runs Alembic | Is not used by the API |
| `yogii_app` | Read and write application tables (used by the API and seed) | Create or drop tables; update or delete audit events, security events, risk assessments, feature snapshots, state transitions or callback records (migration 0003) |

The database runs on an internal Docker network with no published port.

## HTTP hardening

- **Security headers:** `nosniff`, `X-Frame-Options: DENY`, a strict CSP (`default-src 'none'` on API responses), `Referrer-Policy: no-referrer`, `Permissions-Policy`, and `Cache-Control: no-store` on API responses. HSTS is set in production.
- **CORS:** explicit origins only. A wildcard is refused at startup.
- **Callbacks:** unsigned callbacks are never accepted as proof of payment.
- **API docs** are disabled in production.
- **Startup checks.** In production, the API refuses to start with development secrets, SQLite, insecure cookies or `DB_AUTO_CREATE`.

## Data minimisation and retention (prototype assumptions)

| Data | Why it's kept | Default retention |
|---|---|---|
| Payment attempts, risk assessments, state transitions, audit events | Payment record and audit trail | Not deleted by the prototype. Real periods must come from the sponsor bank's and the applicable legal requirements. |
| Feature snapshots (numeric model inputs, no personal data) | Explain and review past decisions | 180 days (`RETENTION_FEATURE_SNAPSHOT_DAYS`) |
| Security events | Detect abuse | 365 days (`RETENTION_SECURITY_EVENT_DAYS`) |
| Transaction-graph edges | Model input (90-day lookback) | 90 days (`RETENTION_GRAPH_EDGE_DAYS`) |

`python -m backend.scripts.retention [--dry-run]` applies these periods. Schedule it daily, and run it with the migrator role, since the app role can't delete audit data.

The model only reads the sender's own history and aggregate receiver counts. It uses no contacts, location services or device identifiers from the user's device.

## Known gaps before any real use

- **Encryption keys** come from environment variables, not an HSM or KMS, and key rotation is designed for but not automated.
- **Rate limits and lockout** are in-memory and per process.
- **No MFA** on sign-in.
- **No admin or review tooling.** Deliberately out of scope for the MVP.
- **Not reviewed or tested by an independent party:** no penetration test, independent code review or compliance review has been done.
