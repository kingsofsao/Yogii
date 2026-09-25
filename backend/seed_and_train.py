from pathlib import Path
import random
import json
import numpy as np
import pandas as pd
import xgboost as xgb
from datetime import datetime, timedelta

from database import Base, engine, SessionLocal
from models import User, Recipient, Transaction

random.seed(42)
np.random.seed(42)

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "model"
MODEL_DIR.mkdir(exist_ok=True)

FEATURE_COLUMNS = [
    "amount", "avg_amount", "amount_ratio", "max_amount", "max_ratio",
    "transactions_today", "amount_today", "transactions_1h", "recipient_count",
    "new_recipient", "unusual_hour", "high_velocity", "graph_degree",
    "recipient_seen", "hour"
]

def make_dataset(n=5000):
    rows = []
    for _ in range(n):
        avg = float(np.random.lognormal(mean=np.log(1100), sigma=0.55))
        amount = float(np.random.lognormal(mean=np.log(avg), sigma=0.9))
        max_amount = float(max(avg * np.random.uniform(1.5, 5.0), amount * np.random.uniform(0.4, 1.2)))
        tx_today = int(np.random.poisson(3))
        amount_today = float(avg * max(tx_today, 1) * np.random.uniform(0.6, 1.8))
        tx_1h = int(np.random.poisson(1.1))
        recipient_count = int(np.random.poisson(2))
        new_recipient = int(recipient_count == 0)
        unusual_hour = int(random.random() < 0.12)
        high_velocity = int(tx_1h >= 4)
        graph_degree = max(1, int(np.random.poisson(4)))
        recipient_seen = int(not new_recipient)
        hour = random.randrange(24)

        ratio = amount / max(avg, 1.0)
        max_ratio = amount / max(max_amount, 1.0)

        # Synthetic ground truth for a realistic UPI fraud detection model
        logit = (
            -4.0
            + 0.32 * ratio
            + 1.35 * new_recipient
            + 1.15 * high_velocity
            + 0.9 * unusual_hour
            + 0.55 * max_ratio
            + 0.10 * tx_today
            + np.random.normal(0, 0.8)
        )
        p = 1.0 / (1.0 + np.exp(-logit))
        fraud = int(random.random() < p)

        rows.append([
            amount, avg, ratio, max_amount, max_ratio, tx_today, amount_today,
            tx_1h, recipient_count, new_recipient, unusual_hour, high_velocity,
            graph_degree, recipient_seen, hour, fraud
        ])

    cols = FEATURE_COLUMNS + ["fraud"]
    return pd.DataFrame(rows, columns=cols)

def compute_roc_auc(y_true, y_score):
    order = np.argsort(y_score)[::-1]
    y_sorted = np.asarray(y_true)[order]
    n_pos = np.sum(y_sorted == 1)
    n_neg = len(y_sorted) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    cum_tp = np.cumsum(y_sorted)
    return float(np.sum(cum_tp[y_sorted == 0]) / (n_pos * n_neg))

def train():
    df = make_dataset(5000)
    df.to_csv(BASE_DIR / "training_dataset.csv", index=False)

    shuffled_idx = np.random.permutation(len(df))
    split_idx = int(0.8 * len(df))
    train_idx = shuffled_idx[:split_idx]
    test_idx = shuffled_idx[split_idx:]

    train_df = df.iloc[train_idx]
    test_df = df.iloc[test_idx]

    dtrain = xgb.DMatrix(train_df[FEATURE_COLUMNS], label=train_df["fraud"], feature_names=FEATURE_COLUMNS)
    dtest = xgb.DMatrix(test_df[FEATURE_COLUMNS], label=test_df["fraud"], feature_names=FEATURE_COLUMNS)

    params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": 5,
        "eta": 0.05,
        "subsample": 0.85,
        "colsample_bytree": 0.9,
        "seed": 42,
    }

    evals = [(dtrain, "train"), (dtest, "eval")]
    model = xgb.train(params, dtrain, num_boost_round=260, evals=evals, verbose_eval=False)

    preds = model.predict(dtest)
    y_test = test_df["fraud"].values
    auc = compute_roc_auc(y_test, preds)
    acc = float(np.mean((preds >= 0.5) == y_test))

    print(f"ROC-AUC: {auc:.4f}")
    print(f"Accuracy: {acc:.4f}")

    model_path = MODEL_DIR / "fraud_model.json"
    model.save_model(str(model_path))
    print(f"Saved: {model_path}")
    return model

def seed_database():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if db.query(User).count() == 0:
        user = User(
            name="Surya Demo User",
            upi_id="surya@demo",
            phone="9999999999",
            balance=25000.0,
            created_at=datetime.utcnow() - timedelta(days=420),
        )
        db.add(user)

        recipients = [
            Recipient(upi_id="rahul@upi", name="Rahul", trust_level="trusted"),
            Recipient(upi_id="amazon@upi", name="Amazon Demo", trust_level="trusted"),
            Recipient(upi_id="canteen@upi", name="Campus Canteen", trust_level="trusted"),
            Recipient(upi_id="newmerchant@upi", name="New Merchant", trust_level="unknown"),
        ]
        db.add_all(recipients)
        db.commit()

        user = db.query(User).first()
        now = datetime.utcnow()
        demo_transactions = [
            ("rahul@upi", 500, 0),
            ("amazon@upi", 1200, 1),
            ("canteen@upi", 350, 2),
            ("rahul@upi", 700, 3),
            ("amazon@upi", 900, 4),
        ]

        for recipient, amount, days_ago in demo_transactions:
            db.add(Transaction(
                user_id=user.id,
                recipient_upi=recipient,
                amount=amount,
                timestamp=now - timedelta(days=days_ago),
                device_id="demo-device",
                location="Chennai",
                status="SUCCESS",
                fraud_probability=0.03,
                risk_score=3.0,
                decision="ALLOW",
                reasons=json.dumps(["Normal historical transaction"])
            ))
        db.commit()

    db.close()

if __name__ == "__main__":
    train()
    seed_database()
    print("Database seeded.")

