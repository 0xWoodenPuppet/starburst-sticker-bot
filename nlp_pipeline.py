"""
NLP Moderation & Toxicity Classification Pipeline
===================================================
An end-to-end Natural Language Processing pipeline for detecting toxicity,
spam, harassment, and rule violations in online community messages.

Methodology:
1. Data Synthesis & Curation: Representative community corpus (safe vs. toxic/scam).
2. NLP Preprocessing: URL/mention/numeric entity normalization, lowercasing, regex cleaning.
3. Feature Engineering: Hybrid Word (1-2 ngrams) + Character Subword (3-5 ngrams) TF-IDF.
4. Model Benchmarking: Multinomial Naive Bayes vs. Calibrated Logistic Regression.
5. Evaluation & Diagnostics: Confusion matrix, ROC curve, Top predictive n-grams.
6. Model Export: Serialized joblib pipeline for sub-millisecond offline inference.

Outputs saved to nlp_output/ for the academic project report and live bot integration.
"""

import os
import re
import json
import random
import asyncio
import numpy as np
import pandas as pd
import joblib

from db import mod_reports

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_curve,
    roc_auc_score,
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
)

OUTPUT_DIR = "nlp_output"
MODEL_DIR = os.path.join(OUTPUT_DIR, "models")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════
#  STEP 1 — Corpus Construction (Safe vs. Toxic)
# ══════════════════════════════════════════════════════════════════════════

async def build_dataset() -> pd.DataFrame:
    """Builds a curated, balanced dataset of online community chat messages.

    Classes:
        0: Safe / Benign (study tasks, focus sessions, casual greetings, Q&A)
        1: Toxic / Violation (insults, harassment, scam links, crypto spam, abuse)
    """
    random.seed(42)
    np.random.seed(42)

    # Base templates for Safe messages (Class 0)
    safe_templates = [
        "Starting a {duration} min focus session on {subject}, let's get to work!",
        "Going to study {subject} for {duration} minutes today.",
        "Working on my {subject} assignment and taking notes.",
        "Review: Completed {num} questions in {subject}, session felt great.",
        "Planted a {tree} tree for {duration} min with the study group.",
        "Time to put down your phone and get back to work! Enter my room code: {code} to plant a {tree} with me!",
        "Join my study room here: https://forestapp.cc/join-room?token={code}",
        "Good morning everyone! Hope you all have a productive study day.",
        "Does anyone have notes or practice problems for {subject}?",
        "How do I track my session streaks with the bot?",
        "Finished {num} hours of deep work today, feeling accomplished.",
        "Taking a short 10 minute break to grab water, back soon.",
        "Good luck with your exams everyone, we got this!",
        "Thanks for planting with me, that was a super focused session.",
        "Can someone join a {duration} minute pomodoro room with me?",
        "Reading chapter {num} of {subject} textbook.",
        "Review: Finished reading and highlighted key concepts in {subject}.",
        "I love this community, helped me build a consistent study habit.",
        "What tree are you all planting today? I picked the cedar tree.",
        "Reviewing calculus integration formulas and practice tests.",
        "Writing my literature essay thesis statement and outline.",
        "Coding my web development homework in Python and React.",
        "Hey everyone, let's keep the momentum going this evening!",
        "Just finished my daily reading challenge check-in.",
        "Review: Completed flashcards for organic chemistry.",
        "Anyone studying for the GRE or IELTS this weekend?",
        "Taking a 5 min stretch break after a solid {duration} min sprint.",
        "Where can I find the leaderboard rankings for this week?",
        "Great session team, see you all for tomorrow's challenge.",
        "Organizing my study schedule for midterms next week."
    ]

    subjects = [
        "Calculus", "Linear Algebra", "Data Structures", "Organic Chemistry",
        "Physics Kinematics", "Biology Genetics", "World History", "Macroeconomics",
        "Machine Learning", "Psychology", "Statistics", "Computer Networks"
    ]
    durations = [15, 25, 30, 45, 50, 60, 90, 120]
    trees = ["Cherry Blossom", "Cedar", "Ginkgo", "Oak", "Weeping Willow", "Moon Tree", "Maple"]
    codes = ["3K7MQGESG", "4A2TUQJSG", "7BJUHTSG", "9284FDS", "CDM7CXSG", "CYJRHXSG"]

    safe_samples = []
    for _ in range(600):
        tmpl = random.choice(safe_templates)
        sample = tmpl.format(
            duration=random.choice(durations),
            subject=random.choice(subjects),
            tree=random.choice(trees),
            code=random.choice(codes),
            num=random.randint(1, 20)
        )
        safe_samples.append((sample, 0))

    # Base templates for Toxic / Violation messages (Class 1)
    toxic_templates = [
        "You are an absolute idiot and nobody likes you, get out of here.",
        "Shut up you stupid clown, you have zero brain cells.",
        "Go cry somewhere else you pathetic loser.",
        "Nobody cares about your dumb notes, kill yourself.",
        "You are completely worthless, stop talking in this group.",
        "F*** you and your stupid study session.",
        "What a total retard, why are you even in this university?",
        "You piece of trash, delete your account and leave.",
        "Stop spamming your pathetic life here, nobody asked.",
        "Shut your f***ing mouth before someone makes you.",
        "You're a brainless moron who will never pass any exam.",
        "Get lost you filthy troll, you disgust everyone here.",
        "Drop out of school you lazy degenerate.",
        "I hate you so much, you are the most annoying person alive.",
        "Kill yourself you pathetic excuse of a student.",
        # Scams & Crypto Fraud
        "FREE BITCOIN GIVEAWAY! CLICK HERE NOW TO DOUBLE YOUR MONEY: https://scam-crypto-bonus.xyz",
        "Make $5,000 daily working from home with zero investment! DM me on WhatsApp: +123456789",
        "Invest $100 in my crypto trading bot and withdraw $2,000 in 2 hours guaranteed!",
        "Exclusive Telegram airdrop claim 500 TON tokens for free right now: https://t.me/free_ton_airdrop",
        "Send 0.05 ETH to my wallet address and get 0.5 ETH back instantly! Promo ending soon!",
        "CashApp flip glitch! Turn $20 into $500 in 15 minutes! DM @fast_cash_glitch",
        "Hacked credit card dumps and verified PayPal accounts for sale cheap, contact @carding_king",
        "Earn $1,000 passive income every single day automatically: http://wealth-matrix-scam.ru",
        "Claim your $750 Shein / Amazon gift card immediately at https://giftcard-claim-now.top",
        # Malicious spam & unauthorized promos
        "Hot single girls in your city want to hook up tonight! Click here: http://adult-date-hookup.xyz",
        "Join my private 18+ leaks channel for free hot videos: https://t.me/xxx_leak_hub",
        "Buy cheap Telegram members, bot views, and fake likes at https://smm-cheap-boost.com",
        "Leaked midterm exam papers and answer keys for sale! Guaranteed 100% score, message me.",
        "Pay for homework and essay writing services, guaranteed A+ grade: https://essay-plagiarize.biz",
        "Free Netflix, Disney+, and Spotify lifetime accounts DM me right now!",
        "Spamming random links check out my stream and donate money: twitch.tv/spammer_bot"
    ]

    toxic_samples = []
    # Expand templates with variations and permutations
    for _ in range(600):
        base = random.choice(toxic_templates)
        # Add slight variations (casing, exclamation, leading phrases)
        variation_type = random.randint(1, 4)
        if variation_type == 1:
            msg = base.upper()
        elif variation_type == 2:
            msg = f"HEY LISTEN: {base} !!!"
        elif variation_type == 3:
            msg = f"{base} Check it out now!"
        else:
            msg = base
        toxic_samples.append((msg, 1))

    # Combine synthetic baseline with real-world Telegram mod reports (Active Learning)
    real_samples = await fetch_real_reports_from_db()
    all_data = safe_samples + toxic_samples + real_samples
    random.shuffle(all_data)

    df = pd.DataFrame(all_data, columns=["text", "label"])
    dataset_path = os.path.join(OUTPUT_DIR, "moderation_dataset.csv")
    df.to_csv(dataset_path, index=False)
    print(f"Dataset generated: {len(df)} total samples ({sum(df['label'] == 0)} safe, {sum(df['label'] == 1)} toxic)")
    if real_samples:
        print(f"  Includes {len(real_samples)} human-verified samples from live Telegram moderation.")
    print(f"Saved to: {dataset_path}")
    return df


async def fetch_real_reports_from_db() -> list[tuple[str, int]]:
    """Pulls human-verified moderation reports from MongoDB mod_reports (Active Learning loop)."""
    real_samples = []
    try:
        cursor = mod_reports.find({"admin_verdict": {"$in": ["CONFIRMED", "REJECTED"]}})
        async for doc in cursor:
            text = doc.get("message_text", "").strip()
            verdict = doc.get("admin_verdict")
            if text:
                label = 1 if verdict == "CONFIRMED" else 0
                real_samples.append((text, label))
    except Exception as e:
        print(f"Notice: Could not query MongoDB mod_reports ({e}). Proceeding with baseline corpus.")
    return real_samples

# ══════════════════════════════════════════════════════════════════════════
#  STEP 2 — NLP Text Preprocessing
# ══════════════════════════════════════════════════════════════════════════

def clean_text(text: str) -> str:
    """Applies canonical NLP text preprocessing:
    - Normalizes URLs to `_URL_`
    - Normalizes user mentions to `_MENTION_`
    - Normalizes numerical amounts / currency to `_NUM_`
    - Strips excess punctuation while preserving subword structure
    - Lowercases text
    """
    if not isinstance(text, str):
        return ""

    # Replace URLs
    text = re.sub(r"https?://\S+|www\.\S+", " _URL_ ", text)
    # Replace Telegram / Twitter handles
    text = re.sub(r"@\w+", " _MENTION_ ", text)
    # Replace currency & numbers
    text = re.sub(r"[\$£€]\s*\d+([.,]\d+)?", " _NUM_ ", text)
    text = re.sub(r"\b\d+\b", " _NUM_ ", text)
    # Replace repeated punctuation (e.g., '!!!!' -> '!')
    text = re.sub(r"([!?,.]){2,}", r" \1 ", text)
    # Strip excess whitespace
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text

# ══════════════════════════════════════════════════════════════════════════
#  STEP 3 — Hybrid TF-IDF Feature Extraction & Model Benchmarking
# ══════════════════════════════════════════════════════════════════════════

def train_and_evaluate(df: pd.DataFrame):
    """Builds the hybrid TF-IDF feature pipeline, trains benchmark models,
    evaluates classification performance, and exports plots & artifacts.
    """
    print("\n--- Preprocessing Text Corpus ---")
    df["cleaned_text"] = df["text"].apply(clean_text)

    X = df["cleaned_text"]
    y = df["label"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Hybrid Feature Union: Word N-Grams (1-2) + Subword Char N-Grams (3-5)
    # Word n-grams capture semantic phrases ("free money", "shut up")
    # Character n-grams capture obfuscation, leetspeak, and morphemes ("f*ck", "idi0t")
    feature_union = FeatureUnion([
        ("word_tfidf", TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=2500,
            sublinear_tf=True
        )),
        ("char_tfidf", TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            max_features=2500,
            sublinear_tf=True
        ))
    ])

    print("\n--- Benchmarking NLP Classifiers (5-Fold Stratified Cross-Validation) ---")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # 1. Multinomial Naive Bayes Baseline
    nb_pipe = Pipeline([
        ("features", feature_union),
        ("clf", MultinomialNB(alpha=0.1))
    ])
    nb_scores = cross_val_score(nb_pipe, X_train, y_train, cv=cv, scoring="f1")
    print(f"1. Multinomial Naive Bayes   - Mean F1: {nb_scores.mean():.4f} (±{nb_scores.std():.4f})")

    # 2. Calibrated Logistic Regression
    lr_pipe = Pipeline([
        ("features", feature_union),
        ("clf", LogisticRegression(C=1.5, max_iter=1000, random_state=42))
    ])
    lr_scores = cross_val_score(lr_pipe, X_train, y_train, cv=cv, scoring="f1")
    print(f"2. Calibrated Logistic Reg.  - Mean F1: {lr_scores.mean():.4f} (±{lr_scores.std():.4f})")

    # Select Logistic Regression (superior calibrated probability estimates)
    selected_pipeline = lr_pipe
    selected_pipeline.fit(X_train, y_train)

    # Test set predictions
    y_pred = selected_pipeline.predict(X_test)
    y_prob = selected_pipeline.predict_proba(X_test)[:, 1]

    # Metrics
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred)
    rec = recall_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    auc = roc_auc_score(y_test, y_prob)

    print("\n" + "=" * 60)
    print("  FINAL NLP TEST SET EVALUATION")
    print("=" * 60)
    print(f"  Accuracy  : {acc:.4f}")
    print(f"  Precision : {prec:.4f}")
    print(f"  Recall    : {rec:.4f}")
    print(f"  F1 Score  : {f1:.4f}")
    print(f"  ROC-AUC   : {auc:.4f}")
    print("\nDetailed Classification Report:\n")
    print(classification_report(y_test, y_pred, target_names=["Safe (0)", "Toxic (1)"]))

    # Save metrics JSON
    metrics = {
        "model": "Hybrid TF-IDF + Logistic Regression",
        "accuracy": round(acc, 4),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1_score": round(f1, 4),
        "roc_auc": round(auc, 4),
        "cv_mean_f1": round(float(lr_scores.mean()), 4)
    }
    with open(os.path.join(OUTPUT_DIR, "metrics_summary.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 4 — Academic Figures & Visualizations
    # ══════════════════════════════════════════════════════════════════════════

    sns.set_theme(style="whitegrid", palette="muted")

    # Figure 1: Confusion Matrix
    cm = confusion_matrix(y_test, y_pred)
    plt.figure(figsize=(6, 5))
    sns.heatmap(
        cm, annot=True, fmt="d", cmap="Blues", cbar=False,
        xticklabels=["Safe (0)", "Toxic (1)"],
        yticklabels=["Safe (0)", "Toxic (1)"]
    )
    plt.title(f"NLP Toxicity Confusion Matrix\n(Accuracy: {acc*100:.1f}%, F1: {f1:.3f})", fontsize=12, pad=12)
    plt.xlabel("Predicted Label", fontsize=11)
    plt.ylabel("Ground Truth", fontsize=11)
    plt.tight_layout()
    cm_path = os.path.join(OUTPUT_DIR, "confusion_matrix.png")
    plt.savefig(cm_path, dpi=300)
    plt.close()
    print(f"Generated plot: {cm_path}")

    # Figure 2: ROC Curve
    fpr, tpr, _ = roc_curve(y_test, y_prob)
    plt.figure(figsize=(6, 5))
    plt.plot(fpr, tpr, color="#2b5c8f", lw=2.5, label=f"Logistic Regression (AUC = {auc:.3f})")
    plt.plot([0, 1], [0, 1], color="#999999", lw=1.5, linestyle="--", label="Random Classifier")
    plt.xlim([0.0, 1.0])
    plt.ylim([0.0, 1.05])
    plt.xlabel("False Positive Rate", fontsize=11)
    plt.ylabel("True Positive Rate (Recall)", fontsize=11)
    plt.title("Receiver Operating Characteristic (ROC)", fontsize=12, pad=12)
    plt.legend(loc="lower right", frameon=True)
    plt.tight_layout()
    roc_path = os.path.join(OUTPUT_DIR, "roc_curve.png")
    plt.savefig(roc_path, dpi=300)
    plt.close()
    print(f"Generated plot: {roc_path}")

    # Figure 3: Top Predictive N-Gram Features
    # Extract feature names from both transformers in FeatureUnion
    word_features = selected_pipeline.named_steps["features"].transformer_list[0][1].get_feature_names_out()
    char_features = selected_pipeline.named_steps["features"].transformer_list[1][1].get_feature_names_out()
    all_feature_names = np.concatenate([word_features, char_features])
    coefficients = selected_pipeline.named_steps["clf"].coef_[0]

    # Top 12 Toxic vs Top 12 Safe
    top_toxic_idx = np.argsort(coefficients)[-12:]
    top_safe_idx = np.argsort(coefficients)[:12]

    features_to_plot = np.concatenate([top_safe_idx, top_toxic_idx])
    feat_names = all_feature_names[features_to_plot]
    feat_coefs = coefficients[features_to_plot]
    colors = ["#2b8257" if c < 0 else "#c0392b" for c in feat_coefs]

    plt.figure(figsize=(9, 6))
    y_pos = np.arange(len(feat_names))
    plt.barh(y_pos, feat_coefs, color=colors, align="center")
    plt.yticks(y_pos, [f"'{f}'" for f in feat_names], fontsize=10)
    plt.axvline(0, color="#333333", linestyle="--", alpha=0.7)
    plt.xlabel("Logistic Regression Coefficient Weight", fontsize=11)
    plt.title("Top Predictive N-Gram Features (Green = Safe, Red = Toxic)", fontsize=12, pad=12)
    plt.tight_layout()
    top_feat_path = os.path.join(OUTPUT_DIR, "top_features.png")
    plt.savefig(top_feat_path, dpi=300)
    plt.close()
    print(f"Generated plot: {top_feat_path}")

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 5 — Model Artifact Serialization
    # ══════════════════════════════════════════════════════════════════════════

    model_artifact_path = os.path.join(MODEL_DIR, "nlp_toxicity_pipeline.joblib")
    joblib.dump(selected_pipeline, model_artifact_path)
    print(f"\nModel pipeline artifact successfully saved to: {model_artifact_path}")
    print(f"File size: {os.path.getsize(model_artifact_path) / 1024:.2f} KB (Offline sub-millisecond inference)")

    return selected_pipeline


async def train_nlp_pipeline():
    """Runs the training pipeline, fits on latest data, and exports updated artifacts to disk."""
    df = await build_dataset()
    return train_and_evaluate(df)


async def main():
    print("=" * 60)
    print("  STARBURST BOT — NLP MODERATION & TOXICITY PIPELINE")
    print("=" * 60)
    await train_nlp_pipeline()
    print("\n✅ NLP Pipeline complete. All artifacts and figures exported.")


if __name__ == "__main__":
    asyncio.run(main())
