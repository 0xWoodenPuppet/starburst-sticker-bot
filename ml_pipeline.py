"""
Multi-Stage ML Pipeline for Focus Session Analysis
=====================================================
Stage 1: K-Means Clustering — Groups user tasks into study categories
Stage 2: Random Forest Classifier — Predicts whether a user will complete
         their session review (follow-through) or skip it.

Dataset: 13,900+ real focus session records from MongoDB (Starburst Telegram Bot)
"""

import asyncio
import os
import re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # non-interactive backend so plots save to file
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    accuracy_score,
    ConfusionMatrixDisplay,
)
from sklearn.preprocessing import LabelEncoder

from db import sessions

OUTPUT_DIR = "ml_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════
#  STEP 1 — Extract & Clean Data from MongoDB
# ══════════════════════════════════════════════════════════════════════════

async def fetch_data() -> pd.DataFrame:
    """Pull all ended sessions from MongoDB and flatten into a per-participant DataFrame.
    
    Only includes sessions where at least one user joined and wrote a task.
    Target: did the user follow through and write a review note? (1 = yes, 0 = no)
    """
    rows = []
    cursor = sessions.find({"phase": "ended"})
    async for s in cursor:
        session_id = str(s["_id"])
        duration = s.get("duration", 0)
        tree = (s.get("tree") or "unknown").lower()
        created_at = s.get("created_at")
        participants = s.get("participants", {})

        if not created_at or not participants:
            continue

        hour = created_at.hour
        day_of_week = created_at.weekday()  # 0=Mon, 6=Sun

        for uid, p in participants.items():
            task = (p.get("task") or "").strip()
            note = (p.get("note") or "").strip()

            if not task:
                continue  # skip participants who didn't write a task

            rows.append({
                "session_id": session_id,
                "user_id": uid,
                "duration": duration,
                "tree": tree,
                "hour": hour,
                "day_of_week": day_of_week,
                "task": task,
                "task_word_count": len(task.split()),
                "task_char_count": len(task),
                "completed_review": 1 if note else 0,  # TARGET
            })

    df = pd.DataFrame(rows)
    print(f"✅ Fetched {len(df)} participant-session rows from MongoDB")
    print(f"   Completed review (1): {(df['completed_review'] == 1).sum()}")
    print(f"   Skipped review  (0): {(df['completed_review'] == 0).sum()}")
    return df


# ══════════════════════════════════════════════════════════════════════════
#  STEP 2 — Stage 1: K-Means Clustering on Task Text
# ══════════════════════════════════════════════════════════════════════════

def cluster_tasks(df: pd.DataFrame, n_clusters: int = 5) -> pd.DataFrame:
    """
    Use TF-IDF + K-Means to cluster task descriptions into study categories.
    """
    print("\n" + "═" * 60)
    print("  STAGE 1: K-MEANS TASK CLUSTERING")
    print("═" * 60)

    task_texts = df["task"].values
    print(f"📝 Tasks to cluster: {len(task_texts)}")

    if len(task_texts) < n_clusters:
        print("⚠️  Not enough tasks to cluster. Assigning all to cluster 0.")
        df["task_cluster"] = 0
        return df

    # TF-IDF vectorization
    tfidf = TfidfVectorizer(max_features=500, stop_words="english")
    tfidf_matrix = tfidf.fit_transform(task_texts)

    # K-Means clustering
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    cluster_labels = kmeans.fit_predict(tfidf_matrix)

    df["task_cluster"] = cluster_labels

    # Print top keywords per cluster
    feature_names = tfidf.get_feature_names_out()
    print(f"\n🏷️  {n_clusters} Task Clusters Discovered:\n")
    cluster_names = {}
    for i in range(n_clusters):
        center = kmeans.cluster_centers_[i]
        top_indices = center.argsort()[-8:][::-1]
        top_words = [feature_names[j] for j in top_indices]
        count = (cluster_labels == i).sum()
        cluster_names[i] = top_words[0].title()
        print(f"   Cluster {i} ({count} tasks): {', '.join(top_words)}")
    
    # Print review completion rate per cluster
    print(f"\n📊 Review Completion Rate per Cluster:\n")
    for i in range(n_clusters):
        cluster_data = df[df["task_cluster"] == i]
        rate = cluster_data["completed_review"].mean() * 100
        count = len(cluster_data)
        print(f"   Cluster {i}: {rate:.1f}% completion rate ({count} sessions)")

    # ── Cluster distribution bar chart ──
    fig, ax = plt.subplots(figsize=(8, 5))
    cluster_counts = pd.Series(cluster_labels).value_counts().sort_index()
    colors = sns.color_palette("viridis", n_clusters)
    bars = ax.bar(cluster_counts.index, cluster_counts.values, color=colors, edgecolor="white")
    ax.set_xlabel("Task Cluster", fontsize=12)
    ax.set_ylabel("Number of Tasks", fontsize=12)
    ax.set_title("Task Cluster Distribution (K-Means + TF-IDF)", fontsize=14, fontweight="bold")
    ax.set_xticks(range(n_clusters))
    for bar, count in zip(bars, cluster_counts.values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2, 
                str(count), ha="center", va="bottom", fontweight="bold")
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "cluster_distribution.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"\n📊 Cluster distribution chart saved → {path}")

    return df


# ══════════════════════════════════════════════════════════════════════════
#  STEP 3 — Stage 2: Random Forest Classifier
# ══════════════════════════════════════════════════════════════════════════

def train_classifier(df: pd.DataFrame):
    """
    Train a Random Forest to predict session review completion.
    Target: completed_review (1 = user wrote a note after session, 0 = skipped)
    Features: duration, hour, day_of_week, tree, task_word_count, task_cluster
    """
    print("\n" + "═" * 60)
    print("  STAGE 2: RANDOM FOREST CLASSIFICATION")
    print("═" * 60)

    # Encode 'tree' as a numeric category
    le = LabelEncoder()
    df["tree_encoded"] = le.fit_transform(df["tree"])

    features = ["duration", "hour", "day_of_week", "tree_encoded", "task_word_count", "task_cluster"]
    X = df[features].values
    y = df["completed_review"].values

    print(f"\n📐 Feature matrix shape: {X.shape}")
    print(f"   Target: completed_review=1 → {y.sum()}, skipped=0 → {(y == 0).sum()}")

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )
    print(f"   Train: {len(X_train)} | Test: {len(X_test)}")

    # Train Random Forest
    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=12,
        random_state=42,
        class_weight="balanced",
    )
    clf.fit(X_train, y_train)
    y_pred = clf.predict(X_test)

    # ── Metrics ──
    acc = accuracy_score(y_test, y_pred)
    print(f"\n🎯 Accuracy: {acc:.4f} ({acc * 100:.1f}%)\n")
    print("📋 Classification Report:\n")
    report = classification_report(y_test, y_pred, target_names=["Skipped Review", "Completed Review"])
    print(report)

    # ── Confusion Matrix ──
    cm = confusion_matrix(y_test, y_pred)
    fig, ax = plt.subplots(figsize=(6, 5))
    disp = ConfusionMatrixDisplay(cm, display_labels=["Skipped Review", "Completed Review"])
    disp.plot(ax=ax, cmap="Blues", values_format="d")
    ax.set_title("Confusion Matrix — Review Completion Prediction", fontsize=12, fontweight="bold")
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "confusion_matrix.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"📊 Confusion matrix saved → {path}")

    # ── Feature Importance ──
    importances = clf.feature_importances_
    sorted_idx = np.argsort(importances)
    readable_names = {
        "duration": "Session Duration",
        "hour": "Hour of Day",
        "day_of_week": "Day of Week",
        "tree_encoded": "Tree Type",
        "task_word_count": "Task Word Count",
        "task_cluster": "Task Cluster (K-Means)",
    }

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = sns.color_palette("magma", len(features))
    labels = [readable_names.get(features[i], features[i]) for i in sorted_idx]
    ax.barh(labels, importances[sorted_idx],
            color=[colors[i] for i in range(len(sorted_idx))],
            edgecolor="white")
    ax.set_xlabel("Importance", fontsize=12)
    ax.set_title("Feature Importance — Random Forest", fontsize=14, fontweight="bold")
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "feature_importance.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"📊 Feature importance chart saved → {path}")

    # ── Review Completion by Hour of Day ──
    fig, ax = plt.subplots(figsize=(10, 5))
    hourly = df.groupby("hour")["completed_review"].agg(["mean", "count"])
    hourly = hourly[hourly["count"] >= 3]  # filter noise
    bar_colors = sns.color_palette("coolwarm", len(hourly))
    ax.bar(hourly.index, hourly["mean"], color=bar_colors, edgecolor="white")
    ax.set_xlabel("Hour of Day (UTC)", fontsize=12)
    ax.set_ylabel("Review Completion Rate", fontsize=12)
    ax.set_title("Session Review Completion Rate by Hour of Day", fontsize=14, fontweight="bold")
    ax.set_xticks(hourly.index)
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "completion_by_hour.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"📊 Completion by hour chart saved → {path}")

    # ── Review Completion by Duration ──
    fig, ax = plt.subplots(figsize=(8, 5))
    dur_data = df.groupby("duration")["completed_review"].agg(["mean", "count"])
    dur_data = dur_data[dur_data["count"] >= 3]
    ax.bar(dur_data.index.astype(str), dur_data["mean"], color="#4ECDC4", edgecolor="white")
    ax.set_xlabel("Session Duration (minutes)", fontsize=12)
    ax.set_ylabel("Review Completion Rate", fontsize=12)
    ax.set_title("Session Review Completion Rate by Duration", fontsize=14, fontweight="bold")
    plt.xticks(rotation=45)
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "completion_by_duration.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"📊 Completion by duration chart saved → {path}")

    # ── Review Completion by Day of Week ──
    fig, ax = plt.subplots(figsize=(8, 5))
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_data = df.groupby("day_of_week")["completed_review"].agg(["mean", "count"])
    ax.bar([day_names[i] for i in dow_data.index], dow_data["mean"], 
           color=sns.color_palette("Set2", 7), edgecolor="white")
    ax.set_xlabel("Day of Week", fontsize=12)
    ax.set_ylabel("Review Completion Rate", fontsize=12)
    ax.set_title("Session Review Completion Rate by Day of Week", fontsize=14, fontweight="bold")
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "completion_by_day.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"📊 Completion by day chart saved → {path}")

    return clf, acc


# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════

async def main():
    print("🚀 Multi-Stage ML Pipeline — Focus Session Analysis")
    print("=" * 60)
    print("Prediction Target: Will a user complete their post-session review?")
    print("=" * 60)

    # Step 1: Fetch data
    df = await fetch_data()

    if df.empty:
        print("❌ No data found. Exiting.")
        return

    # Step 2: Stage 1 — Cluster tasks
    df = cluster_tasks(df, n_clusters=5)

    # Step 3: Stage 2 — Train classifier
    clf, accuracy = train_classifier(df)

    # Save processed dataset to CSV for reference
    csv_path = os.path.join(OUTPUT_DIR, "processed_sessions.csv")
    df.to_csv(csv_path, index=False)
    print(f"\n💾 Processed dataset saved → {csv_path} ({len(df)} rows)")

    print("\n" + "=" * 60)
    print(f"✅ PIPELINE COMPLETE — Accuracy: {accuracy * 100:.1f}%")
    print(f"   All charts and data saved to {OUTPUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
