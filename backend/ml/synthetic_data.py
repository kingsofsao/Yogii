import random
import numpy as np
import pandas as pd
from backend.ml.feature_engine import FEATURE_COLUMNS

def generate_synthetic_fraud_dataset(n_samples: int = 10000, seed: int = 42) -> pd.DataFrame:
    """
    Generates clearly labelled SYNTHETIC training data for the Yogii XGBoost fraud risk model.
    
    WARNING:
    This dataset is strictly synthetic and simulated for system demonstration and testing.
    It must NEVER be represented as actual banking fraud or used for real financial risk appraisal.
    """
    random.seed(seed)
    np.random.seed(seed)

    rows = []

    for _ in range(n_samples):
        # Baseline user profile simulation
        avg_30d = float(np.random.lognormal(mean=np.log(1200), sigma=0.5))
        median_30d = avg_30d * np.random.uniform(0.7, 1.1)

        # 88% normal transactions, 12% anomalous/high-risk scenarios
        is_fraud_scenario = (random.random() < 0.12)

        if not is_fraud_scenario:
            # Normal distribution of spending
            amount = float(np.random.lognormal(mean=np.log(avg_30d), sigma=0.4))
            is_new = 1.0 if random.random() < 0.20 else 0.0
            is_fam = 1.0 if not is_new and random.random() < 0.65 else 0.0
            prior_count = float(np.random.poisson(4) if not is_new else 0)
            tx_30m = float(np.random.poisson(0.3))
            tx_24h = float(np.random.poisson(2.5))
            tx_7d = float(max(tx_24h, np.random.poisson(10.0)))
            unusual_hr = 1.0 if random.random() < 0.05 else 0.0
            loc_novelty = 1.0 if random.random() < 0.04 else 0.0
            dev_novelty = 1.0 if random.random() < 0.02 else 0.0
            pass_through = 1.0 if random.random() < 0.01 else 0.0
            hop_count = 1.0 if random.random() < 0.1 else 0.0
            amt_sim = float(np.random.uniform(0.0, 0.4)) if pass_through else 0.0
            time_gap = float(np.random.uniform(12.0, 48.0))
        else:
            # Suspicious patterns: spike in amount, velocity, new recipient, night-time or pass-through
            amount = float(avg_30d * np.random.uniform(3.5, 15.0))
            is_new = 1.0 if random.random() < 0.75 else 0.0
            is_fam = 0.0
            prior_count = float(0 if is_new else 1)
            tx_30m = float(np.random.poisson(3.5))
            tx_24h = float(np.random.poisson(8.0))
            tx_7d = float(max(tx_24h, np.random.poisson(14.0)))
            unusual_hr = 1.0 if random.random() < 0.40 else 0.0
            loc_novelty = 1.0 if random.random() < 0.35 else 0.0
            dev_novelty = 1.0 if random.random() < 0.30 else 0.0
            pass_through = 1.0 if random.random() < 0.30 else 0.0
            hop_count = 2.0 if pass_through else (1.0 if random.random() < 0.3 else 0.0)
            amt_sim = float(np.random.uniform(0.75, 0.98)) if pass_through else 0.0
            time_gap = float(np.random.uniform(0.2, 2.5))

        amount_ratio = amount / max(avg_30d, 1.0)
        std_est = avg_30d * 0.4
        deviation_score = max(0.0, (amount - avg_30d) / max(std_est, 10.0))
        tx_val_30m = amount * tx_30m * np.random.uniform(0.5, 1.2)
        tx_val_24h = amount * max(tx_24h, 1.0) * np.random.uniform(0.6, 1.5)
        tx_val_7d = tx_val_24h * max(tx_7d / max(tx_24h, 1.0), 1.0)

        daily_rate_from_7d = (tx_7d / 7.0) if tx_7d > 0 else 0.5
        velocity_ratio = tx_24h / max(daily_rate_from_7d, 0.1)
        receiver_act = float(np.random.uniform(0.1, 0.9))

        # Latent synthetic risk probability formula
        z = (
            -4.5
            + 0.55 * min(amount_ratio, 10.0)
            + 0.35 * min(deviation_score, 10.0)
            + 1.40 * is_new
            - 1.20 * is_fam
            + 0.65 * tx_30m
            + 0.35 * tx_24h
            + 1.10 * unusual_hr
            + 1.25 * loc_novelty
            + 1.50 * dev_novelty
            + 1.80 * pass_through
            + 0.80 * amt_sim
            + np.random.normal(0, 0.5)
        )
        prob = 1.0 / (1.0 + np.exp(-z))
        label = int(prob >= 0.5)

        row = {
            "amount": float(amount),
            "avg_amount_30d": float(avg_30d),
            "median_amount_30d": float(median_30d),
            "amount_ratio_avg": float(amount_ratio),
            "amount_deviation_score": float(deviation_score),
            "is_new_recipient": float(is_new),
            "is_familiar_recipient": float(is_fam),
            "prior_recipient_tx_count": float(prior_count),
            "tx_count_30m": float(tx_30m),
            "tx_value_30m": float(tx_val_30m),
            "tx_count_24h": float(tx_24h),
            "tx_value_24h": float(tx_val_24h),
            "tx_count_7d": float(tx_7d),
            "tx_value_7d": float(tx_val_7d),
            "unusual_hour": float(unusual_hr),
            "simulated_location_novelty": float(loc_novelty),
            "simulated_device_novelty": float(dev_novelty),
            "short_vs_long_velocity_ratio": float(velocity_ratio),
            "receiver_activity_score": float(receiver_act),
            "graph_hop_count": float(hop_count),
            "graph_amount_similarity": float(amt_sim),
            "graph_time_gap_hours": float(time_gap),
            "graph_pass_through_flag": float(pass_through),
            "label": label
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    return df
