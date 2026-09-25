# Yogii — Secure Digital Payment Platform with Intelligent Fraud Risk Intelligence

> **IMPORTANT SIMULATION & COMPLIANCE NOTICE**
> 
> - **Yogii currently does NOT process real UPI transactions.**
> - **The current implementation uses `MockPaymentProvider`.**
> - **ALL payments run in SIMULATION MODE with strictly simulated balances.**
> - **Real UPI support requires an authorized sponsor-bank/PSP integration and the applicable onboarding, testing, certification, security, compliance, and legal processes.**
> - **Yogii is NOT currently NPCI-approved, RBI-certified, or bank-certified.**
> - **The synthetic XGBoost model does NOT establish real-world fraud performance.**
> - **The risk thresholds (0–29 LOW, 30–59 MEDIUM, 60–84 HIGH, 85–100 VERY_HIGH) are prototype Yogii policy values.**

---

## 1. What Yogii Is

**Yogii** is a secure digital-payment platform engineered with an intelligent, privacy-conscious fraud risk detection system. It provides a real-time risk assessment engine that combines behavioral context, account history, multi-hop transaction graph analysis, and a calibrated XGBoost machine learning model.

The system is designed with a production-grade domain architecture, strict payment invariants, application-level cryptographic security (AES-256-GCM, HMAC blind indexing, Argon2id), and decoupled payment rails so that a sponsor-bank UPI adapter can be plugged in without refactoring the application.

---

## 2. Technical Architecture

```
                       [ Public Client / Browser ]
                                    │
                                    ▼
                         [ Nginx Reverse Proxy ]
                       (Port 80 / Security Headers)
                       ┌────────────┴────────────┐
                       ▼                         ▼
            [ React + Vite Web App ]    [ FastAPI Backend API ]
               (Tailwind/CSS UI)              (Port 8000)
                                                 │
                  ┌──────────────────────────────┼──────────────────────────────┐
                  ▼                              ▼                              ▼
      [ Security & Crypto ]            [ Fraud Risk Engine ]         [ Payment Domain Engine ]
   • AES-256-GCM Encryption       • Feature Engine (23 signals)   • Strict State Machine
   • HMAC-SHA-256 Blind Index     • NetworkX Transaction Graph    • Idempotency Protection
   • Argon2id Password Hashing    • XGBoost Model Inference       • Atomic Balance Invariants
                  │                              │                              │
                  └──────────────────────────────┼──────────────────────────────┘
                                                 ▼
                                     [ Persistence & Rails ]
                                  • PostgreSQL 16 (Alembic)
                                  • Redis 7 (Cache & Tasks)
                                  • MockPaymentProvider Rail
                                  • SponsorBankUPIProvider (Stub)
```

---

## 3. Repository Structure

```
yogii/
├── backend/
│   ├── api/                     # REST API Routers (auth, me, dashboard, payments, recipients, etc.)
│   ├── core/                    # Security, AES-256-GCM encryption, blind indexing, audit, config
│   ├── database/                # SQLAlchemy models and connection engines
│   ├── domain/                  # Payment state machine, invariants, MockPaymentProvider, SponsorBank stub
│   ├── ml/                      # Feature engine, NetworkX graph engine, XGBoost train & inference
│   ├── model/                   # XGBoost booster artifact (.json) and model metadata (.json)
│   ├── scripts/                 # Seed data, database backup, and restore utilities
│   ├── worker/                  # Async worker background tasks
│   ├── tests/                   # Pytest comprehensive test suite (28 passing tests + E2E validation)
│   ├── requirements.txt         # Python dependencies
│   └── Dockerfile               # Multi-stage Python 3.11 container
├── frontend/
│   ├── src/
│   │   ├── api/                 # API client with token management and auth interceptor
│   │   ├── components/          # Reusable UI (Navbar, SimulatedBanner, AuthModal)
│   │   ├── views/               # Screen views (Dashboard, SendMoney, History, Settings)
│   │   ├── App.jsx              # Main React application shell
│   │   └── styles.css           # Modern fintech CSS design system
│   ├── package.json             # React, Vite, Lucide icons, React Router
│   └── Dockerfile               # Multi-stage Node builder & Nginx static server
├── database/
│   └── migrations/              # Alembic database migration scripts (versions/799ec06ed3d1_...)
├── infrastructure/
│   └── nginx/                   # Nginx reverse proxy configuration & security headers
├── scripts/
│   └── dev.ps1                  # PowerShell helper commands for local development
├── docker-compose.yml           # Complete containerization (api, frontend, postgres, redis, proxy)
├── docker-compose.prod.yml      # Hardened production containerization
├── .env.example                 # Environment configuration template
├── Makefile                     # Make commands for developer workflows
└── README.md                    # System documentation
```

---

## 4. Core Security Design

### 4.1. Zero-Plaintext Sensitive PII Policy
Sensitive user data is **never stored in plaintext** in the database:
- **AES-256-GCM Application-Level Encryption:** Sensitive reversible fields (`full_name`, `email`, `phone`, `upi_id`, `device_id`) are encrypted with fresh 96-bit (12-byte) nonces and key version metadata (`v1$nonce$ciphertext`).
- **HMAC-SHA-256 Blind Indexing:** Searchable fields (`email_lookup_hash`, `phone_lookup_hash`, `upi_id_lookup_hash`) are hashed using a separate HMAC secret key after normalization (trimmed and lowercased). Never uses unsalted SHA of low-entropy inputs.
- **Argon2id Password Hashing:** Reversible passwords are never stored. Passwords use memory-hard Argon2id (`time=2`, `mem=19MiB`, `parallelism=1`).

### 4.2. Mandatory Invariant: Never Store Payment Authentication Secrets
Yogii **NEVER** collects, processes, stores, or logs:
- UPI PIN
- Banking passwords
- Debit-card PIN
- Card CVV
- OTP (One-Time Password)
- Internet banking credentials

Incoming API payloads containing any of these keywords are rejected immediately at the Pydantic schema validation boundary with an explicit `HTTP 422` error.

---

## 5. Payment Invariants & State Machine

### 5.1. Explicit Payment States
```
               ┌───────────┐
               │   DRAFT   │
               └─────┬─────┘
                     │
                     ▼
               ┌───────────┐
      ┌───────►│ ASSESSING │────────┐
      │        └─────┬─────┘        │
      │              │              │
      │              ▼              ▼
┌─────┴──────────────┐        ┌───────────┐
│ NEEDS_VERIFICATION │        │  BLOCKED  │ (Terminal: No balance change)
└─────┬──────────────┘        └───────────┘
      │
      ├─────────────────────────────┐
      ▼                             ▼
┌───────────┐                 ┌───────────┐
│  PENDING  │                 │  FAILED   │ (Terminal: No balance change)
└─────┬─────┘                 └───────────┘
      │
      ▼
┌───────────┐
│ COMPLETED │ (Terminal: Balance updated EXACTLY ONCE)
└─────┬─────┘
      │
      ▼
┌───────────┐
│ REVERSED  │
└───────────┘
```

### 5.2. Mandatory Invariants
1. **Blocked Payment:** Must be recorded in database, must NOT become completed, and must NOT change balance.
2. **Failed Payment:** Must be recorded in database, and must NOT change balance.
3. **Completed Payment:** Updates balances **exactly once** using database transactions.
4. **Idempotency Protection:** Payment creation requests require an `idempotency_key`. Retried requests with the same key return the existing payment attempt and never debit the sender twice.

---

## 6. Fraud Feature Engine & Network Graph

### 6.1. 23 Behavioral & Contextual Features
The feature engine extracts 23 signals over multiple historical windows (30 minutes, 24 hours, 7 days, 30 days, 90 days):
- `amount`, `avg_amount_30d`, `median_amount_30d`, `amount_ratio_avg`, `amount_deviation_score`
- `is_new_recipient`, `is_familiar_recipient`, `prior_recipient_tx_count`
- `tx_count_30m`, `tx_value_30m`, `tx_count_24h`, `tx_value_24h`, `tx_count_7d`, `tx_value_7d`
- `unusual_hour` (midnight to 6 AM)
- `simulated_location_novelty`, `simulated_device_novelty`
- `short_vs_long_velocity_ratio`
- `receiver_activity_score`
- `graph_hop_count`, `graph_amount_similarity`, `graph_time_gap_hours`, `graph_pass_through_flag`

### 6.2. NetworkX Transaction Graph
- Directed graph tracking payment edges between users and recipient endpoints.
- Cycle-safe bounded Breadth-First Search (depth 1, depth 2, max depth 3).
- **Pass-Through Detection:** Detects rapid fund dispersal (e.g. A → B → C) where B receives funds and forwards a similar amount (within 25%) to C within a short window.
- **Safe Terminology Policy:** Graph connections are termed "transaction relationship", "intermediary", or "multi-hop connection". NEVER described as "friendship" or "proof of guilt".

---

## 7. Machine Learning XGBoost Pipeline

- **Synthetic Dataset:** Clearly labelled synthetic dataset generated with reproducible seed (`seed=42`).
- **Algorithm:** XGBoost Booster (`objective="binary:logistic"`, `eval_metric=["logloss", "aucpr"]`, `scale_pos_weight` for imbalance handling).
- **Evaluation Metrics (Held-out test set):**
  - **Precision:** 0.9385
  - **Recall:** 0.9231
  - **F1 Score:** 0.9307
  - **PR-AUC:** 0.2090
- **Fail-Fast Invariant:** If the model artifact is missing, the system **FAILS CLEARLY** with `ModelNotAvailableError`. It NEVER silently falls back to hardcoded rules or alternative models.

### 7.1. Yogii Prototype Risk Bands
| Risk Score | Risk Band | Policy Action |
|---|---|---|
| **0 – 29** | `LOW` | Allow simulated payment immediately |
| **30 – 59** | `MEDIUM` | Warning + Demo Verification Challenge |
| **60 – 84** | `HIGH` | Strong Warning + Demo Verification Challenge |
| **85 – 100** | `VERY_HIGH` | Block simulated payment before clearing rail |

---

## 8. Demo User Credentials (Fictional Seed Data)

All demo accounts share the password: `Password123!`

| User Name | Simulated UPI ID | Simulated Balance | Role / Test Scenario |
|---|---|---|---|
| **Yogesh Kumar** | `yogesh@yogii` | ₹45,000.00 | Routine sender, familiar with `rahul@upi` |
| **Visrojit Sharma** | `visrojit@yogii` | ₹35,000.00 | Intermediary node (receives from Yogesh, sends to Dinesh) |
| **Dinesh Patel** | `dinesh@yogii` | ₹28,000.00 | Recipient in pass-through test scenario |

### Pre-Seeded Recipients
- `rahul@upi` — Trusted personal contact (P2P)
- `freshmarket@merchant` — Trusted grocery merchant (P2M)
- `campuscafe@merchant` — Campus dining merchant (P2M)
- `techgadgets@merchant` — Electronics merchant (P2M)
- `crypto_drain@unknown` — Suspicious unverified recipient (Triggers VERY_HIGH risk block)

---

## 9. Quick Start Commands

### Prerequisites
- Python 3.10+
- Node.js 18+ and npm
- Docker and Docker Compose (for containerized deployment)

### 9.1. Run with Docker Compose
```bash
# 1. Copy environment variables
cp .env.example .env

# 2. Build and launch all services (frontend, api, worker, postgres, redis, reverse-proxy)
docker compose up --build
```
Access the application:
- Web App: `http://localhost`
- Backend API Docs: `http://localhost/docs`

---

### 9.2. Run Locally (Without Docker)

#### Backend Setup
```bash
# 1. Activate Python virtual environment
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run database migrations
alembic upgrade head

# 4. Train the synthetic XGBoost model
python -m backend.ml.train

# 5. Seed fictional demo scenarios
python -m backend.scripts.seed

# 6. Start the API server
uvicorn backend.main:app --reload --port 8000
```

#### Frontend Setup
```bash
# In a new terminal:
cd frontend
npm install
npm run dev
```
Open your browser at `http://localhost:5173`.

---

## 10. Running Test Suites

Run the full pytest test suite (28 passing unit & integration tests):
```bash
pytest backend/tests -v
```

Execute the End-to-End Critical Flows Validation (Flows A through F):
```bash
python -m backend.tests.validate_flows
```

---

## 11. Database Backup & Restore

```bash
# Create a database backup (PostgreSQL or SQLite)
python -m backend.scripts.backup

# Restore from a backup file
python -m backend.scripts.restore <path_to_backup_file>
```

---

## 12. Future Sponsor-Bank / Real UPI Requirements

To transition Yogii from **Simulation Mode** to **Live UPI processing**, the following external requirements are mandatory:
1. **Commercial Sponsor-Bank Partnership:** Partnership with an authorized RBI-regulated sponsor bank (e.g. HDFC, ICICI, SBI, Axis).
2. **NPCI TPAP Approval:** Formal registration as a Third-Party Application Provider (TPAP) with the National Payments Corporation of India.
3. **Certified PSP API Integration:** Onboarding with the sponsor bank's certified Payment Service Provider (PSP) gateway specifications.
4. **Hardware Security Module (HSM):** Integration of FIPS 140-2 Level 3 compliant HSMs for bank-grade key management.
5. **NPCI & Cert-In Security Audits:** Formal security assessments, source code reviews, vulnerability testing, and compliance with RBI storage of payment system data directives.
