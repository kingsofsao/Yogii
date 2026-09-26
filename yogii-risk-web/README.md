# Yogii Risk Web

Yogii Risk Web is a browser-only demo of **simulated** UPI-style payments with a
prototype fraud-risk check. Before you enter the demo PIN, each payment gets a
score from 0 to 100, a plain-language explanation and an **OK / Reject** decision.

> **Simulation notice**
>
> - Nothing here is real. Yogii has **no** connection to UPI, NPCI, any bank or any payment app. Balances are demo numbers.
> - Yogii is **not** NPCI-approved, RBI-certified or bank-certified, and it is not production-ready.
> - The risk model was trained on **synthetic data only**. Its numbers say nothing about real-world fraud.
> - The risk bands (0–29 Low, 30–59 Medium, 60–84 High, 85–100 Very high) are **Yogii prototype values**, not RBI, NPCI or bank standards.
> - Payment-graph links are **signals, never proof** of fraud.
> - Yogii never asks for, stores or logs a UPI PIN, OTP, CVV, card PIN or bank password. The app uses a **demo PIN `1234`**, which is not a UPI PIN.

---

## Quick start

The app is one file: `dist/index.html`. It has no install step and no server-side code.

**Option 1: open the file.** Double-click `dist/index.html`, or drag it into Chrome, Edge, Firefox or Safari.

**Option 2: serve it locally** (recommended; some browsers restrict `file://` pages):

```bash
python -m http.server -d dist 8080
# then open http://localhost:8080
```

On **Windows**, use `py` if `python` isn't on your PATH:

```powershell
py -m http.server -d dist 8080
```

If Windows Firewall asks, allow access on **private networks only**.

**On your phone over Wi-Fi:**

1. Connect the phone and the computer to the same Wi-Fi network.
2. Start the server so it listens on all interfaces: `python -m http.server -d dist 8080 --bind 0.0.0.0`
3. Find the computer's local IP address: `ipconfig` on Windows (IPv4 Address), `ipconfig getifaddr en0` on macOS, `hostname -I` on Linux.
4. On the phone, open `http://<that-ip>:8080`, for example `http://192.168.1.20:8080`.

Data lives in the browser's `localStorage`, so each browser and device has its own copy of the demo data.

## Demo accounts (fictional)

| Name | Email | Password | UPI ID | Mobile |
|---|---|---|---|---|
| Yogesh Kumar | `yogesh@demo.yogii` | `Password123!` | `yogesh@yogii` | 9876543210 |
| Visrojit Sharma | `visrojit@demo.yogii` | `Password123!` | `visrojit@yogii` | 9876543211 |
| Dinesh Patel | `dinesh@demo.yogii` | `Password123!` | `dinesh@yogii` | 9876543212 |

Each demo account starts with a simulated ₹3,00,000 and some past payments dated relative to today. Accounts you register also start with ₹3,00,000.

The demo directory also contains these recipients:

| UPI ID | What it is |
|---|---|
| `rahul@upi` | A contact Yogesh has paid many times |
| `freshmarket@merchant`, `campuscafe@merchant`, `techgadgets@merchant` | Merchants |
| `crypto_drain@unknown` | An account on the demo watchlist. Every payment to it is blocked. |

Any other well-formed UPI ID (for example `someone@okbank`) is treated as an unregistered UPI ID.

The demo PIN is **`1234`**.

## Features

- **Accounts:** register, sign in and sign out. Passwords must have 10+ characters with uppercase, lowercase and a number. You also need a valid email and a 10-digit Indian mobile number. Passwords are hashed with PBKDF2-SHA-256 (150,000 iterations, per-user salt) through Web Crypto. Sign-in locks for 60 seconds after 5 failures, error messages are generic, and sessions last 12 hours.
- **Home:** simulated balance with a SIMULATED stamp and a hide-balance toggle, recent activity, a security summary and one-tap demo scenarios.
- **Send money:** pay by UPI ID, mobile number, saved people or merchants. The steps are: confirm recipient → amount (with model limits and demo controls) → risk check → **OK / Reject** → demo verification (Medium and High) → demo PIN → processing → result.
- **Demo controls** on the amount screen: pretend this is a new device or location, pretend it's 2 AM, and choose the demo bank outcome (Success, Failure or Pending). Changing any control recalculates the limits.
- **History:** search, plus filters for status and risk band.
- **Payment detail:** timeline, risk breakdown and technical details (features and component probabilities).
- **Settings:** profile, security, privacy, risk-engine summary, theme (system/light/dark), sign out, and a reset of the demo data (through an accessible dialog).
- **Design:** neutral base with one accent colour, light and dark themes, responsive down to phones (bottom navigation), keyboard-friendly, visible focus rings, labelled inputs and `aria-live` announcements.

### Payments

The payment state machine allows only these transitions. Any other transition throws an error.

```
DRAFT → ASSESSING → NEEDS_VERIFICATION | BLOCKED | PENDING | COMPLETED | FAILED
NEEDS_VERIFICATION → PENDING | COMPLETED | FAILED
PENDING → COMPLETED | FAILED
COMPLETED → REVERSED
BLOCKED, FAILED, REVERSED: terminal
```

`MockPaymentProvider` is the simulated bank. It uses no randomness: the outcome is whatever the demo control says. Settlement is idempotent, and payment creation takes an idempotency key. For a **Pending** payment, **Check status** acts as the demo bank's callback. A duplicate callback never debits twice.

These invariants are covered by the tests:

- Blocked, failed and rejected payments never change balances.
- A completed payment changes balances exactly once.
- A transfer between two Yogii users credits the receiver.

## Demo scenarios

| Scenario | What you should see |
|---|---|
| Yogesh pays `rahul@upi` ₹500 | **Low** (about 5). Completes; the balance drops once. |
| Yogesh pays `techgadgets@merchant` ₹24,500 | **High** (about 66), with "amount above usual" and "new recipient". |
| Any payment to `crypto_drain@unknown` | **Very high**; the receiver side shows High; the limit is ₹0. |
| Yogesh pays `visrojit@yogii` ₹10,000, then Visrojit pays `dinesh@yogii` ₹9,800 | The second payment shows a **2-hop payment chain** and is **High** (about 72), not blocked. |
| Then Dinesh pays `rahul@upi` ₹9,500 | **3-hop chain**, **Very high** (about 98), blocked. |
| Then Yogesh pays `dinesh@yogii` | Indirect path `yogesh → visrojit → dinesh`. |
| Demo bank outcome **Failure** | Payment **Failed**; balance unchanged. |
| Demo bank outcome **Pending**, then **Check status** twice | Debits once. |

The approximate scores assume a daytime payment on the default demo controls.

## How the risk engine works

```
                     payment + sender history (this browser only)
                                     │
        ┌────────────────────────────┼─────────────────────────────┐
        ▼                            ▼                             ▼
  Amount features              Behaviour features            Context features
  log_amount, amount_ratio,    is_new_recipient,             is_night, hour_deviation
  amount_z, share_of_balance,  prior_count, tx_count_30m,    (circular mean of past
  is_round                     value_24h_ratio,              hours), new_device,
                               indirect_connection, is_p2m   account_age_days
        │                            │                             │
        ▼                            ▼                             ▼
  XGBoost (60 trees)           XGBoost (60 trees)            XGBoost (60 trees)
        │ p_amount                   │ p_behavior                  │ p_context
        │                            │                             │
        │      Payment graph ────────┼──── graph score             │
        │      (chain ≤ 3 hops)      │                             │
        │      Receiver side ────────┼──── receiver score          │
        ▼                            ▼                             ▼
          Linear regression over [p_amount, p_behavior, p_context, graph, receiver]
                                     │
                         clip to 0–1, × 100 = score
                                     │
         0–29 LOW │ 30–59 MEDIUM (verify) │ 60–84 HIGH (verify) │ 85–100 VERY_HIGH (blocked)
```

- **XGBoost components:** each component is trained on its own synthetic anomaly label (`binary:logistic`, 60 trees, depth 3, eta 0.2, lambda 1, subsample 0.8, 32-bin histograms, `scale_pos_weight` capped at 4). The browser runs the exported trees directly.
- **Payment chain:** follows inbound payments upstream, at most 3 hops, without revisiting any account. An inbound payment counts when it arrived within the 2 hours before the next payment and is within 25% of its amount. Hops = the number of payments in the chain, including this one. The graph score is `[0, .2, .5, .8][hops] × (0.6 + 0.4 × average similarity)`. Each hop is shown with its own level (High when similarity ≥ 0.9 and the gap ≤ 30 minutes).
- **Indirect connection:** a breadth-first search from sender to recipient over the last 90 days of completed payments. It's used only when the recipient is new to you, and the path is shown.
- **Receiver side:** a watchlisted account scores 1.0. Otherwise, points are added for: an unregistered UPI ID (+0.25), an account under 7 days old (+0.2), 3 or more other payers in 24 hours (+0.25), and outflow of at least 70% of inflow within 24 hours (+0.3). Levels: Normal < 0.3 ≤ Elevated < 0.6 ≤ High. **You see only the level and a generic note, never the receiver's history or balance.**
- **Reasons:** AMOUNT_ABOVE_USUAL, NEW_RECIPIENT, INDIRECT_CONNECTION, HIGH_RECENT_VELOCITY, UNUSUAL_TIME, DEVICE_OR_LOCATION_CHANGE, NEW_ACCOUNT, POSSIBLE_PASS_THROUGH_PATTERN and RECEIVER_SIDE_RISK. Each is shown as plain language, without raw thresholds or weights.
- **Privacy in chains:** only the person who paid you directly is named. Earlier accounts appear as "Another Yogii account".
- **No silent fallback:** if the model file is missing or doesn't match, the app shows "Risk model unavailable" and disables payments. It never falls back to hand-written rules.

## Model-based limits

The amount screen asks the engine about the current sender, recipient and demo controls. It probes increasing amounts on a geometric grid, then binary-searches on a ₹100 grid. For each threshold (30, 60 and 85), it finds the largest amount (rounded down to ₹100) that still scores below it:

| Row | Meaning |
|---|---|
| No extra checks | Up to this amount the score stays Low |
| With demo verification | Up to this amount the score stays below High |
| With a strong warning | Up to this amount the payment is not blocked |
| Above that | The risk check blocks the payment |

Amount entry refuses anything above the ₹1,00,000 demo ceiling or your balance. It also warns before an amount above the blocking limit: if you continue, the risk check blocks the payment and shows why. A watchlisted recipient's limit is ₹0.

## Project structure

```
yogii-risk-web/
  src/index.html  src/styles.css  src/app.js     app source (plain HTML/CSS/JS, no framework)
  models/yogii_risk_model.json                   browser model (trees + stacker + settings)
  models/metrics.json                            evaluation on the synthetic test slice
  models/native/                                 the real xgboost boosters (JSON)
  ml/synthetic.py                                synthetic data generator (seed 42)
  ml/xgb_numpy.py                                numpy implementation of XGBoost
  ml/export_xgboost.py                           real booster -> browser tree format
  ml/train.py                                    training pipeline
  ml/check_scenarios.py                          scores the demo scenarios in Python
  data/synthetic_transactions.csv                the synthetic training data
  scripts/build.py                               inlines everything into dist/index.html
  dist/index.html                                the single self-contained page
  tests/engine.test.js                           node:test engine and payment tests
  tests/e2e_test.py                              Playwright browser test
  docs/MODEL_CARD.md  CHANGELOG.md  Makefile  package.json  requirements.txt
```

## Development

You need Python 3.10+ with numpy, Node 18+, and (for the browser test) Playwright.

```bash
pip install -r requirements.txt       # numpy, xgboost (optional), playwright
python ml/train.py                    # regenerate data + model (reproducible)
python ml/check_scenarios.py          # every line should be OK
python scripts/build.py               # writes dist/index.html
node --test tests/engine.test.js      # engine tests
python tests/e2e_test.py              # browser test
```

`make check` runs all five in order, and `make clean-check` also confirms that `git status` is clean afterwards. If you have Node but no `make`, `npm run check` does the same.

To work on the source without rebuilding, serve the **project root** and open `/src/`:

```bash
python -m http.server 8080    # then open http://localhost:8080/src/
```

`src/index.html` fetches `../models/yogii_risk_model.json`. If you open it from `file://`, the fetch fails and the app correctly shows "Risk model unavailable".

### Training with real XGBoost

```bash
python ml/train.py --engine auto      # default: real xgboost if installed, otherwise ml/xgb_numpy.py
python ml/train.py --engine xgboost   # require real xgboost; stops with a clear error if it's missing
python ml/train.py --engine numpy     # force the numpy implementation
```

With real xgboost, the boosters are saved to `models/native/*.json`. They're converted with `ml/export_xgboost.py`, and training stops if the exported trees disagree with xgboost's own predictions. The committed model was trained with **xgboost 3.2.0** (`"engine"` in the model file).

Training is reproducible: the same seed and engine produce byte-identical `data/`, `models/yogii_risk_model.json` and `models/metrics.json`. The numpy engine gives very close but not identical trees, so switching engines changes the artifact.

## Tests

- `tests/engine.test.js` loads `src/app.js` with minimal browser stubs through the `globalThis.__YOGII_TEST__` hook. It checks:
  - band boundaries and the model file's shape
  - that a missing model fails clearly
  - every demo scenario
  - chain detection, the 3-hop limit, cycles and the indirect path
  - receiver-side signals and balance invariants, including duplicate settlement and duplicate callbacks
  - idempotency, illegal transitions and verification before the PIN
  - that the score at each model limit is really below its threshold, and that a watchlisted recipient's limit is 0
  - registration, PBKDF2 sign-in, lockout and session expiry
- `tests/e2e_test.py` drives Chromium through the whole app:
  - sign-in (including a failed attempt)
  - the limit panel and a demo control
  - refusal of an amount over the ceiling
  - a High payment through OK → verification → PIN
  - the watchlist block and history filters
  - the reset dialog and the phone layout
  - the missing-model screen

  It fails on any page error. The clock is fixed at 14:00 India time so the scores are reproducible.

## Metrics (synthetic data only)

> These numbers measure how well the model recovers **synthetic** labels that we generated ourselves. They are **not** evidence of real-world fraud detection.

From `models/metrics.json` (test slice, 3,600 synthetic rows, positive = synthetic analyst rating ≥ 0.6, decision = score ≥ 60):

| Metric | Value |
|---|---|
| Precision | 0.922 |
| Recall | 0.891 |
| F1 | 0.907 |
| PR-AUC | 0.976 |
| Confusion matrix | TP 475 · FP 40 · FN 58 · TN 3,027 |
| Component PR-AUC | amount 0.977 · behaviour 0.767 · context 0.626 |
| Stacker R² | 0.942 (validation) · 0.941 (test) |
| Stacker weights | p_amount 0.381 · p_behavior 0.293 · p_context 0.149 · graph 0.439 · receiver 0.755 (intercept 0.047) |

## Privacy

- The app never collects, stores or logs a UPI PIN, OTP, CVV, card PIN or bank password. The demo PIN is compared in memory and the field is cleared right away.
- All data (accounts, password hashes, payments) stays in your browser's `localStorage`. The built page's Content Security Policy blocks all network requests.
- Every `localStorage` access is wrapped in `try/catch`, so private windows and blocked storage don't crash the app.
- Senders see only a level and a generic note about a receiver.
- Graph relationships are described as payment chains, indirect connections and intermediaries. They are signals, not proof, and never "friendship".

## Troubleshooting

| Problem | Fix |
|---|---|
| "Risk model unavailable" | You opened `src/index.html` from `file://`. Open `dist/index.html` instead, or serve the project root over HTTP. If `dist/` is missing, run `python scripts/build.py`. |
| Stuck on "Loading…" | JavaScript is disabled, or the browser is very old. Use a current Chrome, Edge, Firefox or Safari. |
| Can't sign in with a demo account | Check the password (`Password123!`). After 5 failures, wait 60 seconds. Settings → Reset demo data restores the accounts. |
| Data disappears | Private windows and "clear site data" wipe `localStorage`. |
| Phone can't reach the server | Use `--bind 0.0.0.0`, put both devices on the same Wi-Fi network, and allow Python through the firewall on private networks. |
| `python ml/train.py --engine xgboost` stops | Install xgboost (`pip install xgboost`), or use `--engine numpy`. |
| E2E can't find a browser | Run `python -m playwright install chromium`, or set `CHROMIUM_PATH` to an existing Chromium binary. |

## Limitations

- Synthetic data and hand-written labels: the model learns a made-up notion of "unusual", not real fraud.
- One browser, one dataset: there is no server, no shared ledger, and no protection against someone editing `localStorage`.
- Client-side password hashing protects only against casual reading of storage. It is not server-grade account security.
- Features only see payments stored in this browser. The receiver-side check sees only the demo directory.
- Limits are probed on a grid. Because tree models are step functions, they are approximate between grid points. The risk check at payment time is what decides.
- Scores depend on the time of day and your recent activity, so they drift slightly from the numbers above if you follow the scenarios at night or after many payments.

## Reusing `ml/` and `models/` in the FastAPI backend

This repository also contains a FastAPI backend (`../backend`). To serve the same model there:

1. Copy or import `ml/synthetic.py` (feature names and definitions) and `ml/check_scenarios.py` (`World.features`, `component`, `chain`, `indirect_path`, `receiver`, `assess`). Together they are a complete Python port of the browser engine.
2. Load `models/yogii_risk_model.json` once at startup. The tree format is framework-free: `{f, t, l, r}` / `{v}`, where `x < t` goes left (compare as float32), and `margin = logit(base_score) + Σ leaves`. You can also load `models/native/*.json` with `xgboost.Booster().load_model(...)`.
3. Build features from the database instead of `localStorage`. Keep the same definitions (30-day average, circular mean of hours, 90-day graph window) so scores match.
4. Keep the rule that a missing or mismatched model is a hard error. Run `ml/check_scenarios.py` in CI against the backend's port.

## What real UPI would require

A real deployment would need all of the following, and more. None of it exists in Yogii today.

- A sponsor bank or licensed Payment Service Provider, and onboarding onto UPI through them under NPCI's rules.
- NPCI certification of the app and its flows, plus the applicable RBI directions (for example on payment security, KYC and data localisation).
- A certified PSP SDK for device binding and PIN capture. **An app like this must never capture the UPI PIN itself.**
- A server-side ledger with real idempotency, reconciliation, dispute and chargeback handling.
- Security audits, penetration testing, incident response, grievance redressal and legal review.
- A risk model trained and validated on real, lawfully obtained data, with fairness, drift and privacy reviews. Its thresholds would be set by the bank's risk policy, not by this prototype.
