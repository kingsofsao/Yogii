# Changelog

All notable changes to Yogii Risk Web. Everything in this project is simulated.

## [1.0.0] - 2026-09-26

### Added
- A single-page, browser-only app (`dist/index.html`) for simulated UPI-style payments. It has no framework and no runtime dependencies.
- **Accounts:**
  - PBKDF2-SHA-256 password hashing with a per-user salt (Web Crypto).
  - Strong-password, email and mobile-number validation.
  - A 60-second lockout after 5 failed sign-ins, generic error messages and 12-hour sessions.
  - Storage in `localStorage`, with every access wrapped in `try/catch`.
- **Fictional demo data:** Yogesh, Visrojit and Dinesh, each with ₹3,00,000 and relative-dated history. The directory has a familiar contact, three merchants and a watchlisted account.
- **Screens:** sign in, register, home, send flow, risk check, demo verification, demo PIN (`1234`, never stored), processing, result, history with filters, payment detail and settings (with an accessible reset dialog).
- **Payment state machine** with explicit legal transitions. Illegal transitions throw.
- **`MockPaymentProvider`:** deterministic outcomes, idempotent settlement, an idempotent "Check status" callback and idempotency keys.
- **Risk engine:**
  - Three XGBoost anomaly components (amount, behaviour, context).
  - Payment-chain detection (at most 3 hops, cycle-safe) and an indirect-connection search.
  - A receiver-side score and a linear-regression stacker.
  - Bands LOW, MEDIUM, HIGH and VERY_HIGH, with plain-language reason codes.
- **Model-based limits:** a geometric probe followed by a binary search, enforced at amount entry together with the ₹1,00,000 demo ceiling and the balance.
- **ML pipeline:**
  - Synthetic data (seed 42).
  - `--engine auto|xgboost|numpy`, with a numpy XGBoost implementation and a booster exporter.
  - A time-based 70/15/15 split, metrics, native boosters and a reproducible artifact.
- `ml/check_scenarios.py`, a Python port of the engine that checks every demo scenario band.
- Tests: `tests/engine.test.js` (node:test) and `tests/e2e_test.py` (Playwright).
- Docs: README, model card and this changelog.
- A Content Security Policy in the built page that allows only its own inline script and no network access.
