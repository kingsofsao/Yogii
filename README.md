# Yogii

Yogii is the foundation for a digital payment app with built-in fraud-risk checks. You manage a payment profile, pick a recipient and enter an amount. Before you authorise the payment, you get a risk score, a risk level and plain-language reasons.

> **Simulation only. Please read this first.**
>
> - Yogii **does not process real payments.** Every account, balance and payment is **simulated**.
> - Yogii is **not connected** to any bank, NPCI, UPI network or payment gateway.
> - Yogii is **not** approved, certified or licensed by NPCI, the RBI, any bank or any other authority. It is **not ready** to process real money.
> - The fraud model is trained on **synthetic, fictional data**. Its metrics say nothing about real-world fraud detection.
> - The risk thresholds are **Yogii prototype values**, not RBI, NPCI or bank standards.
> - Yogii never asks for, stores or logs a **UPI PIN, OTP, card details or bank password.**
>
> Real payments would first need an authorised sponsor bank or PSP, their onboarding and credentials, the required testing and certification, and a current legal and security review. See [Future sponsor-bank / UPI integration](#future-sponsor-bank--upi-integration).

---

## Contents

- [What's in the box](#whats-in-the-box)
- [Run it locally](#run-it-locally)
- [Seed the demo data](#seed-the-demo-data)
- [Train the synthetic XGBoost model](#train-the-synthetic-xgboost-model)
- [What the risk score means](#what-the-risk-score-means)
- [What is simulated](#what-is-simulated)
- [Future sponsor-bank / UPI integration](#future-sponsor-bank--upi-integration)
- [API](#api)
- [Tests](#tests)
- [Back up and restore the database](#back-up-and-restore-the-database)
- [Project layout](#project-layout)
- [Further documentation](#further-documentation)

## What's in the box

| Area | What it does |
|---|---|
| **Web app** (`frontend/`, React + TypeScript + Vite + Tailwind) | Sign-in and registration, a dashboard with the simulated balance, and a send-money flow: recipient → confirm → amount → risk review → demo verification → result. Also payment history and detail, and security and privacy settings. Every screen shows a simulation notice. |
| **API** (`backend/`, FastAPI + Pydantic + SQLAlchemy) | Cookie sessions with CSRF protection, a payment state machine with idempotency keys, rate limits and audit events. |
| **Fraud-risk engine** (`backend/ml/`) | A feature engine, a NetworkX transaction graph, an XGBoost model with isotonic calibration, and user-safe reason codes. |
| **Payment-rail boundary** (`backend/integrations/payments/`) | A typed provider interface, the `MockPaymentProvider`, and a sponsor-bank adapter that deliberately can't be constructed. |
| **Database** (PostgreSQL + Alembic in `database/migrations/`) | Users, demo accounts, directory payees, payment attempts, risk assessments, feature snapshots, graph edges, state transitions, provider callbacks, preferences, model metadata, security and audit events, and app configuration. |
| **Deployment** (`docker-compose.yml`) | Postgres on an internal network, a one-shot migration job, a least-privilege app role, the API, and an nginx web front end. |

## Run it locally

### Option A: Docker Compose (PostgreSQL, closest to a real deployment)

```bash
./scripts/generate-dev-env.sh      # writes .env with random local-only secrets
docker compose up --build          # db -> migrate -> seed -> api -> web
```

Open **http://localhost:8080** and sign in with a [demo account](#seed-the-demo-data).

Compose starts these services in order:

1. `db`: Postgres. It has no published port and sits on an internal-only network.
2. `migrate`: runs `alembic upgrade head` as the schema-owner role.
3. `seed`: adds fictional demo data. It's idempotent and refuses to run in production.
4. `api`: connects as the least-privilege `yogii_app` role.
5. `web`: nginx. It serves the React build and proxies `/api`, so the browser uses a single origin.

### Option B: without Docker (SQLite for quick development)

Requirements: Python 3.11+ and Node 20+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env                     # then replace every <placeholder>, or export the variables
python -m backend.scripts.seed           # creates the SQLite schema and fictional demo data
uvicorn backend.main:app --reload --port 8000

cd frontend && npm ci && npm run dev     # http://localhost:5173 (proxies /api to :8000)
```

The API reads configuration from environment variables. In development, anything unset falls back to safe local defaults. With `APP_ENV=production`, the API refuses to start if any development secret, SQLite or insecure cookie is still configured.

The interactive API docs are at http://localhost:8000/api/docs. They're disabled in production.

**Local development vs. production:**
- Local runs use plain HTTP and `COOKIE_SECURE=false`.
- Any shared or production deployment must terminate TLS in front of `web` and set `COOKIE_SECURE=true`.

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Seed the demo data

```bash
python -m backend.scripts.seed            # empty database only
python -m backend.scripts.seed --reset    # wipe and re-seed (development only)
```

With Docker, the `seed` service runs automatically.

The seed creates **fictional** people, UPI IDs, accounts, histories and transaction-graph links. It then runs every payment through the real service, including about six weeks of backdated history. That means every stored risk score is a genuine model output.

**Demo accounts** (all fictional):

| Name | Sign-in | UPI ID |
|---|---|---|
| Yogesh Kumar | `yogesh@demo.yogii` | `yogesh@yogii` |
| Visrojit Sharma | `visrojit@demo.yogii` | `visrojit@yogii` |
| Dinesh Patel | `dinesh@demo.yogii` | `dinesh@yogii` |

All three use the password `Password123!`.

**Demo scenarios** (the seed prints the outcome of each):

| # | Scenario | Typical outcome |
|---|---|---|
| 1 | Routine payment to a familiar recipient (Yogesh → `rahul@upi`, ₹500) | LOW, completed |
| 2 | Much larger than usual, to a new unverified recipient (₹18,000) | MEDIUM or HIGH, verified |
| 3 | High velocity: five payments in 12 minutes (Dinesh) | Risk rises through the burst |
| 4 | 3 AM, new phone, unfamiliar city (Visrojit) | VERY HIGH, blocked |
| 5 | Possible pass-through: Yogesh → Visrojit ₹15,000, then Visrojit → Dinesh ₹14,700 twelve minutes later | Flagged with `POSSIBLE_PASS_THROUGH_PATTERN`, never blocked on the graph alone |
| 6 | Payment to a watchlisted payee (`crypto_drain@unknown`, ₹40,000) | VERY HIGH, blocked, balance unchanged |
| 7 | Mock bank declines | FAILED, balance unchanged |
| 8 | Same idempotency key replayed | One payment, one debit |

The seed also leaves one PENDING payment, so you can try **Check status**. To try the flow yourself, use the **Simulation controls** on the amount screen: device, location and mock bank outcome.

## Train the synthetic XGBoost model

The trained artifact is committed (`backend/model/2.0.0-synthetic/`). To reproduce it:

```bash
python -m backend.ml.train                           # about 20 s; writes backend/model/<MODEL_VERSION>/
python -m backend.ml.train --export-data data.csv    # also dump the synthetic dataset
python -m backend.ml.evaluate                        # re-check on a fresh synthetic stream
```

**How the pipeline works:**

1. **Data.** `backend/ml/synthetic_data.py` simulates fictional users paying people and merchants over about three months. It injects scripted incidents: account takeover, push-payment scams, velocity drains and mule pass-through chains. It also adds benign look-alikes: big purchases, new phones, travel, late-night payers, and forwarding money for shared bills. Some fraud-shaped incidents are labelled genuine, because in reality many are.
2. **No train/serve skew.** Features come from `backend/ml/features.py`, the same function the API uses. Each payment only sees events before it.
3. **Split.** The data is split by time: train 65%, early stopping 7%, calibration 13%, test 15%.
4. **Training.** XGBoost (`binary:logistic`, `hist`), with `scale_pos_weight` for the class imbalance (about 4% positives).
5. **Calibration.** Isotonic regression on the calibration slice, so the score is a calibrated probability on synthetic data rather than a raw model output.
6. **Artifacts.** `model.json`, `calibration.json` and `metadata.json`. The metadata holds the metrics, gain-based feature importance, parameters and data description.
7. **No fallback.** If XGBoost or the artifact is missing, or the feature schema doesn't match, startup and assessment fail with a clear setup error. Yogii never falls back to rules or another model.

**Current synthetic test metrics** (6,147 synthetic payments, 5% labelled fraud):

| Metric | Value |
|---|---|
| PR-AUC | 0.77 |
| ROC-AUC | 0.97 |
| Brier score | 0.022 raw → 0.016 after calibration |
| At score ≥ 60 (HIGH and above) | Precision 0.81, recall 0.72, F1 0.76 |
| Synthetic fraud rate by band | LOW 0.6%, MEDIUM 53%, HIGH 79%, VERY HIGH 86% |

These numbers describe how well the model recovers labels we generated ourselves. **They are not evidence of real-world performance.** See [docs/RISK_MODEL.md](docs/RISK_MODEL.md).

## What the risk score means

The score is a number from 0 to 100: the model's calibrated probability, on synthetic data, that a payment matches a fraud pattern. The backend then applies a policy with configurable thresholds (`RISK_THRESHOLD_*`):

| Score | Band | What happens (simulation) |
|---|---|---|
| 0–29 | LOW | The payment can continue |
| 30–59 | MEDIUM | Warning and demo verification |
| 60–84 | HIGH | Strong warning and demo verification |
| 85–100 | VERY HIGH | Blocked before mock authorisation; recorded for audit |

**Reasons.** Users see safe reason codes and plain sentences. The reasons come from the model's per-feature contributions, and they never reveal internal rules or anything about the receiver's history. The codes are:
- `AMOUNT_ABOVE_USUAL`
- `NEW_RECIPIENT`
- `HIGH_RECENT_VELOCITY`
- `UNUSUAL_TIME`
- `DEVICE_OR_LOCATION_CHANGE`
- `POSSIBLE_PASS_THROUGH_PATTERN`
- `INDIRECT_TRANSACTION_LINK`
- `RECEIVER_RISK_SIGNAL`
- `LIMITED_HISTORY`

**A graph link is a signal, not proof.** If only transaction-graph signals push a score to VERY HIGH, the policy caps it at HIGH (verify), never block.

**Limitations:**
- The model has never seen a real payment, so its behaviour on real traffic is unknown.
- The synthetic world is simple: few fraud patterns, and hand-picked distributions.
- Scores for accounts with little history rely on a generic baseline.
- Device and location are simulated labels, not real device intelligence.
- The thresholds are arbitrary prototype values.
- A real deployment would need validation on appropriate, lawfully obtained data, fairness and drift monitoring, and a policy approved by the sponsor bank.

## What is simulated

| Item | Status |
|---|---|
| Accounts and balances | **Simulated.** Every user gets a demo balance (₹50,000 for new registrations). |
| Payment execution | **Simulated** by `MockPaymentProvider`: success, failure or pending, chosen with the demo control. |
| Pending → completed | Simulated: the mock rail confirms on the first status check, or through a signed test callback. |
| Recipients, merchants, watchlist | **Fictional** demo directory. Any other UPI ID is shown as "Unverified". |
| Device and location | **Simulated** labels chosen on the amount screen, stored only as keyed hashes. |
| Demo verification | A checklist. It is **not** a bank authentication step and never asks for a PIN or OTP. |
| Training data | **Synthetic.** |

## Future sponsor-bank / UPI integration

The code keeps a hard boundary between Yogii and anything that could move real money (`backend/integrations/payments/`). The full contract is in [docs/INTEGRATION_BOUNDARY.md](docs/INTEGRATION_BOUNDARY.md).

**The provider interface.** `PaymentProvider` defines:
- `initiate_payment`
- `get_payment_status`
- `verify_callback` (signature and freshness)
- `request_reversal` and `get_reversal_status`
- `fetch_settlement_records` (for reconciliation)

**The mock provider.** `MockPaymentProvider` is the only implementation. It is used whenever live mode is off, which is always today.

**The sponsor-bank adapter.** `SponsorBankUPIProvider` is deliberately unimplemented, and constructing it raises an error. It stays that way until an authorised sponsor bank or PSP provides its documentation, credentials and onboarding. Yogii does not invent bank APIs, endpoints or credentials.

**The live-payments flag** is server-side only. Live mode needs all of these in the deployment environment:
- `PAYMENT_MODE=live`
- `LIVE_PAYMENTS_ENABLED=true`
- a named `SPONSOR_BANK_ADAPTER`
- `APP_ENV=production`

Even with all four set, startup fails today because no adapter exists. There's no user setting, API endpoint or database row that can change this. `PATCH /api/settings` rejects any such field.

**Callbacks** go to `POST /api/integrations/payments/callback`. They are accepted only after the provider verifies them. Unsigned, stale, tampered and replayed callbacks are rejected and recorded.

**Authority in live mode.** The sponsor bank and the applicable UPI requirements decide. Yogii's prototype policy could only add friction before submission. It could never override a bank decision, and it assumes nothing about bank certification.

**Real deployment requires**, at minimum:
- sponsor-bank / PSP onboarding;
- the bank's certified authentication journey, so the UPI PIN is never seen by Yogii;
- the testing and certification the bank and the applicable requirements call for;
- model validation on permitted data;
- a current legal, security and privacy review.

None of the security measures in this repository make Yogii compliant or certified on their own.

## API

All routes are under `/api`. Interactive docs are at `/api/docs` in development.

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create a demo user. Sets the session cookie. Rate-limited. |
| POST | `/auth/login` | Sign in with email, mobile or UPI ID. Rate-limited, with lockout after repeated failures. |
| POST | `/auth/logout`, `/auth/logout-all` | End this session, or every session. |
| GET | `/me`, `/me/security-events` | Profile, simulated balance, your own security events. |
| GET | `/dashboard` | Balance, stats, recent payments, money received. |
| GET | `/recipients`, `/recipients/lookup?q=` | Demo payees; look up by UPI ID or mobile (name and type only). |
| POST | `/payments/assess` | Create an attempt and run the risk assessment. Needs an `Idempotency-Key` header. |
| POST | `/payments` | Authorise an assessed attempt (demo verification for MEDIUM/HIGH). Needs an `Idempotency-Key` header. |
| POST | `/payments/{id}/cancel` | Cancel before authorisation. |
| GET | `/payments`, `/payments/{id}`, `/payments/{id}/status` | History (filter by `state` and `band`), detail with timeline, status (asks the rail for PENDING payments). |
| GET | `/model/info` | Model version, synthetic metrics, importance, disclaimer. |
| GET / PATCH | `/settings` | Read-only mode and policy information; update personal preferences only. |
| POST | `/integrations/payments/callback` | Signed rail callbacks (server to server). |
| GET | `/health`, `/ready` | Liveness; readiness (database and model). |

**Request rules:**
- **CSRF:** every unsafe request must send `X-CSRF-Token`, taken from the `yogii_csrf` cookie.
- **Strict bodies:** request bodies reject unknown fields and any PIN, OTP, CVV, card or bank-password field.

## Tests

```bash
pytest backend/tests                   # 123 tests on SQLite
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/yogii_test pytest backend/tests   # same suite on PostgreSQL
cd frontend && npm test                # 18 Vitest + Testing Library tests
cd frontend && npm run typecheck && npm run build
```

The backend tests cover:
- feature creation and missing-history handling;
- graph depth limits and cycles;
- risk-band boundaries, and very-high-risk blocking;
- balance invariants for failed, blocked, pending and reversed payments;
- idempotent creation and authorisation, and a concurrent-authorisation race (PostgreSQL);
- authentication, authorisation and CSRF;
- invalid inputs, secret-field rejection and rate limits;
- mock-provider success, failure and pending, and callback verification;
- the live-mode guard;
- the seed scenarios and ledger;
- migrations matching the models.

`make check` runs the backend and frontend checks together.

## Back up and restore the database

**Docker (PostgreSQL):**

```bash
docker compose exec -T db pg_dump -U postgres --format=custom yogii > backups/yogii-$(date +%F).dump
docker compose stop api
docker compose exec -T db pg_restore -U postgres --clean --if-exists --single-transaction -d yogii < backups/yogii-2026-01-01.dump
docker compose run --rm migrate && docker compose start api
```

**Without Docker:**

```bash
python -m backend.scripts.backup                        # pg_dump custom format, or a consistent SQLite copy (mode 600)
python -m backend.scripts.restore backups/<file> --yes  # then: alembic upgrade head
```

Backups contain encrypted personal data. Store the encryption keys **separately** from the backups; either one alone is useless. Retention, backup schedules and incident response are covered in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Project layout

```
backend/
  api/                 FastAPI routers (auth, me, dashboard, recipients, payments, settings, model, health, callbacks)
  core/                config (fail-closed), sessions, CSRF, rate limits, encryption, validation, audit
  database/            SQLAlchemy models and session
  domain/              payment service, state machine, prototype risk policy, reconciliation
  integrations/payments/   provider interface, MockPaymentProvider, SponsorBankUPIProvider (unimplemented)
  ml/                  features, NetworkX graph, synthetic data, training, inference
  model/<version>/     trained artifacts (synthetic)
  scripts/             seed, backup, restore, retention, reconcile
  tests/               pytest suite
database/migrations/   Alembic (0002: v2 schema, 0003: append-only audit grants)
frontend/              React + TypeScript + Tailwind app, Vitest tests, nginx config
infrastructure/postgres/init/   database role setup (least privilege)
docs/                  deployment, security and privacy, integration boundary, risk model
yogii-risk-web/        separate browser-only prototype (static page, see its README)
```

## Further documentation

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): TLS, secrets, database roles, backups, restore drills, audit logs, retention, incident response.
- [docs/SECURITY_AND_PRIVACY.md](docs/SECURITY_AND_PRIVACY.md): controls, what is and isn't stored, data-retention assumptions.
- [docs/INTEGRATION_BOUNDARY.md](docs/INTEGRATION_BOUNDARY.md): the provider contract and what a sponsor-bank adapter must do.
- [docs/RISK_MODEL.md](docs/RISK_MODEL.md): model card, features, metrics, limitations.
