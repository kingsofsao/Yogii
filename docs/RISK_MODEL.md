# Model card: Yogii prototype fraud-risk model 2.0.0-synthetic

> **Trained on synthetic, fictional data only.** Not validated on real payments. Not suitable for real risk decisions. The thresholds are Yogii prototype values, not RBI, NPCI or bank standards.

## Summary

| | |
|---|---|
| Task | Estimate how likely it is that a simulated payment matches a fraud pattern, before authorisation |
| Model | XGBoost `binary:logistic` (`hist`, depth 4, eta 0.05, subsample and column sample 0.85, up to 400 rounds with early stopping), then isotonic calibration |
| Output | `risk_score` 0–100: the calibrated probability on synthetic data × 100 |
| Artifacts | `backend/model/2.0.0-synthetic/{model.json, calibration.json, metadata.json}` |
| Code | `backend/ml/{features,graph_engine,synthetic_data,train,inference}.py` |

## Intended use

- Demonstrating a pre-authorisation risk check with understandable reasons, inside Yogii's **simulated** payment flow.
- Testing the plumbing a real model would need: shared features, versioned artifacts, calibration, an audit trail, and a fail-closed loader.

**Not for:** real payment, credit or account decisions; judging whether a person is a fraudster; any claim about real-world fraud rates.

## Data

`synthetic_data.py` generates a **synthetic** event stream. A month of burn-in runs first so that established users have real histories, followed by 88 emitted days.

**Population:** about 500 fictional users (some joining during the period), 90 merchants, 700 contacts, 14 watchlisted payees and 18 mule accounts (half newly opened, half established).

**Normal activity:**
- Poisson daily payment counts;
- a personal time of day and a usual amount per user;
- favourite payees, with occasional new ones.

**Benign look-alikes**, all labelled 0:
- big purchases from merchants;
- first payments to new, unregistered payees;
- new phones and travel;
- late-night users;
- forwarding money for shared bills, which creates legitimate pass-through shapes.

**Incidents**, labelled 1 when "confirmed":
- account takeover (new device, often a new city and night-time; larger amounts);
- push-payment scams (the user's own device; large or round amounts to new payees, fake shops, mules or watchlisted payees);
- velocity drains (bursts of payments);
- mule pass-through chains (forwarding 88–99% within minutes, sometimes through established accounts).

**Deliberate ambiguity.** Only some fraud-shaped incidents are confirmed: 55–90% depending on type, 97% for watchlisted payees. The rest are genuine payments with the same shape. There's 2% label noise on fraud and 0.2% on normal payments.

**Split:** time-based. Train 65% (26,633 rows), early stopping 7%, calibration 13%, test 15% (6,147 rows). The test slice is 5% fraud.

## Features (schema v2)

All features come from `compute_features()`, which the API uses too. They only see events before the payment.

| Group | Features |
|---|---|
| Amount | `amount`, `amount_log`, sender average and median over 7/30/90 days (`FEATURE_HISTORY_DAYS`), ratio to each, z-score |
| History | `sender_history_count`, `history_missing` (cold start uses a generic baseline) |
| Recipient | `is_new_recipient`, `prior_pair_count`, `is_p2m` |
| Velocity | Count and value in 30 minutes and 24 hours, 24-hour vs. long-term rate |
| Time, device, location | Circular hour deviation, `unusual_hour`, simulated device and location novelty |
| Receiver (aggregates only, never shown to the sender) | Registered, watchlisted, account age, distinct payers in 24 h, inflow count in 24 h, outflow/inflow ratio in 24 h |
| Transaction graph (NetworkX, depth 2 by default, 3 optional) | Hop count, amount similarity, time gap, pass-through flag, indirect link through an intermediary |

## Results on the synthetic test slice

| Metric | Value |
|---|---|
| PR-AUC | 0.768 |
| ROC-AUC | 0.970 |
| Brier score | 0.0220 raw → 0.0164 calibrated |
| Score ≥ 60 (HIGH+) | Precision 0.809, recall 0.724, F1 0.764 (TP 220, FP 52, FN 84, TN 5,791) |
| Score ≥ 85 (block) | Precision 0.864, recall 0.188 |
| Synthetic fraud rate by band | LOW 0.6% (5,786 rows) · MEDIUM 52.8% (89) · HIGH 79.1% (206) · VERY HIGH 86.4% (66) |

**Most important features (gain):**
- `is_new_recipient` 0.41
- `receiver_account_age_days` 0.12
- `graph_time_gap_minutes` 0.06
- `tx_value_30m_ratio` 0.05
- `receiver_on_watchlist` 0.04

All metrics are in `metadata.json`, including per-scenario results and the full importance list.

**Interpretation.** The model recovers the patterns we wrote into the generator, so the numbers mostly measure the generator's own consistency. They say nothing about real fraud.

## Decision policy (separate from the model)

`backend/domain/risk_policy.py` maps scores to bands using backend-configurable thresholds:

| Score | Band | Action |
|---|---|---|
| 0–29 | LOW | Allow |
| 30–59 | MEDIUM | Warn and require demo verification |
| 60–84 | HIGH | Strong warning and verification |
| 85–100 | VERY HIGH | Block before mock authorisation |

If the only reasons behind a VERY HIGH score are transaction-graph codes, the policy downgrades it to HIGH (verify): a graph link is never treated as proof. In a live deployment, the sponsor bank's approved policy would be authoritative.

## Explanations

Reason codes come from XGBoost per-feature contributions (`pred_contribs`). Contributions are grouped by reason and gated on the feature actually being unusual. The text is fixed and generic: no thresholds, no internal rules, no receiver details.

## Known limitations and risks

- **Synthetic distributions.** They are simple, and real fraud looks different and keeps changing.
- **Unmeasured bias.** Real payment habits vary by region, occupation, age and income. Signals such as "new recipient" or "late-night" could disadvantage people whose normal behaviour differs.
- **Weak cold start.** New accounts rely on a fixed baseline.
- **Simulated context.** Device and location are demo labels.
- **Training-time graph depth.** The model was trained with graph depth 2. At depth 3, `graph_hop_count = 3` is outside the training distribution.
- **Calibration and thresholds.** Calibration is fitted on synthetic data, and the thresholds were chosen for a demo.

## What real use would require

- Lawfully obtained, representative data under a proper data-protection basis.
- Out-of-time validation.
- Fairness analysis.
- Drift monitoring and a retraining process.
- Human review of blocked cases.
- A process for users to contest decisions.
- A policy owned and approved by the sponsor bank.

## Reproduce

```bash
python -m backend.ml.train     # deterministic for a fixed seed and XGBoost version (single-threaded)
python -m backend.ml.evaluate  # fresh synthetic stream with another seed
```
