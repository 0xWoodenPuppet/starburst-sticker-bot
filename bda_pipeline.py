"""BDA Pipeline — User Engagement Analytics & Retention.

ETL pipeline using MongoDB Aggregation Framework:
  1. Extract: Pull raw session data from MongoDB
  2. Transform: Normalize trees, compute per-user engagement metrics, retention cohorts
  3. Load: Store aggregated results into user_analytics & global_analytics collections

Dataset: ~45,000 focus session records from the Starburst Telegram Bot.

Usage:
    python bda_pipeline.py          # Run full pipeline
    python bda_pipeline.py --dry    # Analyze only, don't write to MongoDB
"""

import asyncio
import argparse
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from db import sessions, user_analytics, channel_analytics, global_analytics
from services.tree_normalizer import normalize_tree

OUTPUT_DIR = "bda_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════
#  STAGE 1 — EXTRACT & TRANSFORM
# ══════════════════════════════════════════════════════════════════════════

async def extract_sessions() -> pd.DataFrame:
    """Pull all ended sessions and flatten into a per-session DataFrame.

    Extracts both user-hosted and channel-hosted sessions.
    Deduplicates cross-group multi-shares (identical tree and duration within 3 minutes by same host).
    Converts timestamps to GMT+3.
    """
    rows = []
    cursor = sessions.find(
        {"phase": "ended", "duration": {"$gt": 0}, "created_at": {"$exists": True}},
    )

    async for s in cursor:
        created_at = s.get("created_at")
        if not created_at:
            continue

        # Ensure timezone-aware UTC
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # Standardize to GMT+3 (AST)
        created_at_gmt3 = created_at + timedelta(hours=3)

        host_id = s.get("host_id")
        try:
            hid_int = int(host_id)
            if hid_int < 0:
                entity_type = "channel"
            elif hid_int > 0:
                entity_type = "user"
            else:
                continue
        except (ValueError, TypeError):
            continue

        duration = s.get("duration", 0)
        tree_raw = (s.get("tree") or "unknown").strip()
        tree_normalized = normalize_tree(tree_raw)
        participants = s.get("participants", {})
        if not isinstance(participants, dict):
            participants = {}

        rows.append({
            "session_id": str(s["_id"]),
            "host_id": str(host_id),
            "host_username": s.get("host_username", ""),
            "entity_type": entity_type,
            "tree": tree_normalized,
            "duration": duration,
            "chat_id": str(s.get("chat_id", "")),
            "created_at": created_at_gmt3,
            "date": created_at_gmt3.date(),
            "hour": created_at_gmt3.hour,
            "day_of_week": created_at_gmt3.weekday(),  # 0=Mon, 6=Sun
            "participants": participants,
            "participant_count": len(participants),
            "has_task": any(p.get("task") for p in participants.values()) if participants else False,
            "has_review": any(p.get("note") for p in participants.values()) if participants else False,
        })

    raw_df = pd.DataFrame(rows)
    if raw_df.empty:
        return raw_df

    raw_df["created_at"] = pd.to_datetime(raw_df["created_at"])
    raw_df["date"] = pd.to_datetime(raw_df["date"])

    # Sort chronologically per host
    raw_df = raw_df.sort_values(by=["host_id", "created_at"]).reset_index(drop=True)

    # Detect duplicate cross-group shares: same host, same duration, same tree within 3 minutes
    time_diff = raw_df.groupby("host_id")["created_at"].diff()
    same_dur = raw_df["duration"] == raw_df.groupby("host_id")["duration"].shift(1)
    same_tree = raw_df["tree"] == raw_df.groupby("host_id")["tree"].shift(1)
    is_dup = (time_diff <= timedelta(minutes=3)) & same_dur & same_tree

    # Group into duplicate clusters
    raw_df["cluster_id"] = (~is_dup).cumsum()

    # Collapse clusters by unioning participants
    def _merge_cluster(g):
        first = g.iloc[0].to_dict()
        if len(g) > 1:
            merged_parts = {}
            for p in g["participants"]:
                if isinstance(p, dict):
                    merged_parts.update(p)
            first["participants"] = merged_parts
            first["participant_count"] = len(merged_parts)
            first["has_task"] = any(p.get("task") for p in merged_parts.values()) if merged_parts else False
            first["has_review"] = any(p.get("note") for p in merged_parts.values()) if merged_parts else False
            first["shared_groups_count"] = len(g)
        else:
            first["shared_groups_count"] = 1
        return pd.Series(first)

    df = raw_df.groupby("cluster_id", as_index=False, group_keys=False).apply(_merge_cluster)
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["date"] = pd.to_datetime(df["date"])

    print(f"✅ Extracted {len(raw_df)} total raw sessions")
    print(f"   Deduplicated to {len(df)} unique sessions ({len(raw_df) - len(df)} cross-group shares merged)")
    print(f"   Unique personal users: {df[df['entity_type'] == 'user']['host_id'].nunique()}")
    print(f"   Unique study channels: {df[df['entity_type'] == 'channel']['host_id'].nunique()}")
    print(f"   Date range (GMT+3): {df['date'].min().date()} → {df['date'].max().date()}")
    return df


# ══════════════════════════════════════════════════════════════════════════
#  STAGE 2 — PER-USER ENGAGEMENT METRICS
# ══════════════════════════════════════════════════════════════════════════

def _compute_streaks(dates: list) -> tuple[int, int]:
    """Compute current streak and best streak from a sorted list of unique dates."""
    if not dates:
        return 0, 0

    unique_dates = sorted(set(dates))
    today = (datetime.now(timezone.utc) + timedelta(hours=3)).date()

    # Best streak
    best = 1
    current = 1
    for i in range(1, len(unique_dates)):
        if (unique_dates[i] - unique_dates[i - 1]).days == 1:
            current += 1
            best = max(best, current)
        else:
            current = 1

    # Current streak (from today backwards)
    current_streak = 0
    check_date = today
    for d in reversed(unique_dates):
        if d == check_date:
            current_streak += 1
            check_date -= timedelta(days=1)
        elif d < check_date:
            break

    return current_streak, best


def compute_user_metrics(df: pd.DataFrame, label: str = "USER") -> pd.DataFrame:
    """Compute per-entity engagement metrics (users or channels)."""
    print("\n" + "═" * 60)
    print(f"  STAGE 2: PER-{label} ENGAGEMENT METRICS")
    print("═" * 60)

    if df.empty:
        return pd.DataFrame()

    today = (datetime.now(timezone.utc) + timedelta(hours=3)).date()
    user_metrics = []

    for host_id, group in df.groupby("host_id"):
        sorted_dates = sorted(group["date"].dt.date.tolist())
        first_session = sorted_dates[0]
        last_session = sorted_dates[-1]
        active_days = len(set(sorted_dates))
        total_days_span = max((last_session - first_session).days, 1)

        current_streak, best_streak = _compute_streaks(sorted_dates)

        # Sessions per week
        weeks_active = max(total_days_span / 7, 1)
        sessions_per_week = len(group) / weeks_active

        # Most used duration and tree
        top_duration = group["duration"].mode().iloc[0] if not group["duration"].mode().empty else 0
        
        valid_trees = group[group["tree"] != "unknown"]["tree"]
        top_tree = valid_trees.mode().iloc[0] if not valid_trees.mode().empty else "None"

        # Peak hour
        peak_hour = group["hour"].mode().iloc[0] if not group["hour"].mode().empty else 0

        # Peak day
        peak_day = group["day_of_week"].mode().iloc[0] if not group["day_of_week"].mode().empty else 0

        # Tree diversity
        unique_trees = group["tree"].nunique()

        # Review rate (only for sessions where they had participants)
        sessions_with_tasks = group[group["has_task"]].shape[0]
        sessions_with_reviews = group[group["has_review"]].shape[0]
        review_rate = sessions_with_reviews / sessions_with_tasks if sessions_with_tasks > 0 else None

        # Duration trend: compare avg duration of first half vs second half
        if len(group) >= 4:
            mid = len(group) // 2
            sorted_group = group.sort_values("created_at")
            early_avg = sorted_group.iloc[:mid]["duration"].mean()
            late_avg = sorted_group.iloc[mid:]["duration"].mean()
            duration_trend = "increasing" if late_avg > early_avg * 1.1 else (
                "decreasing" if late_avg < early_avg * 0.9 else "stable"
            )
        else:
            duration_trend = "insufficient_data"

        # Churn risk: days since last session (in GMT+3)
        days_since_last = (today - last_session).days

        user_metrics.append({
            "user_id": str(host_id),
            "username": group["host_username"].iloc[0],
            "total_sessions": len(group),
            "total_focus_minutes": int(group["duration"].sum()),
            "avg_duration": round(group["duration"].mean(), 1),
            "top_duration": int(top_duration),
            "top_tree": top_tree,
            "unique_trees": unique_trees,
            "peak_hour": int(peak_hour),
            "peak_day": int(peak_day),
            "active_days": active_days,
            "sessions_per_week": round(sessions_per_week, 2),
            "current_streak": current_streak,
            "best_streak": best_streak,
            "review_rate": round(review_rate, 3) if review_rate is not None else None,
            "duration_trend": duration_trend,
            "days_since_last": days_since_last,
            "first_session": first_session.isoformat(),
            "last_session": last_session.isoformat(),
        })

    metrics_df = pd.DataFrame(user_metrics)
    print(f"📊 Computed metrics for {len(metrics_df)} {label.lower()} entities")
    print(f"   Avg sessions: {metrics_df['total_sessions'].mean():.1f}")
    print(f"   Avg focus time: {metrics_df['total_focus_minutes'].mean():.0f} min")
    print(f"   Avg streak (best): {metrics_df['best_streak'].mean():.1f} days")
    return metrics_df


# ══════════════════════════════════════════════════════════════════════════
#  STAGE 3 — RETENTION COHORT ANALYSIS
# ══════════════════════════════════════════════════════════════════════════

def compute_retention_cohorts(df: pd.DataFrame) -> dict:
    """Group users by first-session week, track % still active at week N."""
    print("\n" + "═" * 60)
    print("  STAGE 3: RETENTION COHORT ANALYSIS")
    print("═" * 60)

    # Find first session date per user
    first_sessions = df.groupby("host_id")["date"].min().reset_index()
    first_sessions.columns = ["host_id", "first_date"]
    first_sessions["cohort_week"] = first_sessions["first_date"].dt.to_period("W").dt.start_time

    # Merge back
    df_with_cohort = df.merge(first_sessions[["host_id", "cohort_week"]], on="host_id")

    # For each user, find which weeks they were active
    df_with_cohort["active_week"] = df_with_cohort["date"].dt.to_period("W").dt.start_time
    df_with_cohort["weeks_since_first"] = (
        (df_with_cohort["active_week"] - df_with_cohort["cohort_week"]).dt.days / 7
    ).astype(int)

    # Build retention table
    cohort_sizes = first_sessions.groupby("cohort_week")["host_id"].nunique()
    retention_data = (
        df_with_cohort.groupby(["cohort_week", "weeks_since_first"])["host_id"]
        .nunique()
        .reset_index()
    )
    retention_data.columns = ["cohort_week", "weeks_since_first", "active_users"]

    # Compute retention rates
    retention_table = {}
    for _, row in retention_data.iterrows():
        cohort = str(row["cohort_week"].date())
        week_n = int(row["weeks_since_first"])
        cohort_size = cohort_sizes.get(row["cohort_week"], 1)
        rate = round(row["active_users"] / cohort_size * 100, 1)

        if cohort not in retention_table:
            retention_table[cohort] = {"cohort_size": int(cohort_size), "weeks": {}}
        retention_table[cohort]["weeks"][str(week_n)] = {
            "active_users": int(row["active_users"]),
            "retention_rate": rate,
        }

    # Print summary
    print(f"📊 {len(retention_table)} weekly cohorts analyzed")
    # Show avg retention at key weeks
    for week_n in [1, 2, 4, 8]:
        rates = []
        for cohort, data in retention_table.items():
            w = data["weeks"].get(str(week_n))
            if w and data["cohort_size"] >= 3:  # Only meaningful cohorts
                rates.append(w["retention_rate"])
        if rates:
            avg = sum(rates) / len(rates)
            print(f"   Week {week_n} avg retention: {avg:.1f}% (from {len(rates)} cohorts)")

    return retention_table


# ══════════════════════════════════════════════════════════════════════════
#  STAGE 4 — GLOBAL METRICS
# ══════════════════════════════════════════════════════════════════════════

def compute_global_metrics(df: pd.DataFrame, user_metrics: pd.DataFrame, retention: dict, channel_metrics: pd.DataFrame = None) -> dict:
    """Compute global engagement metrics across all community sessions."""
    print("\n" + "═" * 60)
    print("  STAGE 4: GLOBAL METRICS")
    print("═" * 60)

    now = datetime.now(timezone.utc)
    today = (now + timedelta(hours=3)).date()

    # DAU / WAU / MAU
    last_1d = df[df["date"].dt.date >= today - timedelta(days=1)]["host_id"].nunique()
    last_7d = df[df["date"].dt.date >= today - timedelta(days=7)]["host_id"].nunique()
    last_30d = df[df["date"].dt.date >= today - timedelta(days=30)]["host_id"].nunique()

    # Top trees (all time, normalized)
    top_trees = (
        df[df["tree"] != "unknown"]["tree"].value_counts().head(15)
        .reset_index()
        .rename(columns={"index": "tree", "tree": "name", "count": "sessions"})
        .to_dict("records")
    )

    # Duration distribution
    duration_dist = (
        df["duration"].value_counts().sort_index()
        .reset_index()
        .rename(columns={"index": "duration", "duration": "minutes", "count": "sessions"})
        .to_dict("records")
    )

    # Hourly distribution (GMT+3)
    hourly_dist = (
        df["hour"].value_counts().sort_index()
        .reset_index()
        .rename(columns={"index": "hour", "hour": "hour_val", "count": "sessions"})
        .to_dict("records")
    )

    # Weekly session trend (last 12 weeks)
    df["week"] = df["date"].dt.to_period("W").dt.start_time
    weekly_trend = (
        df.groupby("week")
        .agg(sessions=("session_id", "count"), unique_users=("host_id", "nunique"))
        .tail(12)
        .reset_index()
    )
    weekly_trend["week"] = weekly_trend["week"].dt.strftime("%Y-%m-%d")
    weekly_trend = weekly_trend.to_dict("records")

    # Avg retention at key milestones
    retention_summary = {}
    for week_n in [1, 2, 4, 8]:
        rates = []
        for cohort, data in retention.items():
            w = data["weeks"].get(str(week_n))
            if w and data["cohort_size"] >= 3:
                rates.append(w["retention_rate"])
        if rates:
            retention_summary[f"week_{week_n}"] = round(sum(rates) / len(rates), 1)

    # Top study channels
    top_channels = []
    if channel_metrics is not None and not channel_metrics.empty:
        top_channels = (
            channel_metrics.sort_values(by="total_sessions", ascending=False)
            .head(10)[["user_id", "username", "total_sessions", "total_focus_minutes", "top_tree"]]
            .rename(columns={"user_id": "channel_id", "username": "channel_title"})
            .to_dict("records")
        )

    user_count = df[df["entity_type"] == "user"]["host_id"].nunique()
    channel_count = df[df["entity_type"] == "channel"]["host_id"].nunique()

    global_doc = {
        "computed_at": now,
        "total_sessions": len(df),
        "total_users": user_count,
        "total_channels": channel_count,
        "total_focus_minutes": int(df["duration"].sum()),
        "total_focus_hours": round(df["duration"].sum() / 60, 1),
        "dau": last_1d,
        "wau": last_7d,
        "mau": last_30d,
        "avg_sessions_per_user": round(len(df[df["entity_type"] == "user"]) / max(user_count, 1), 1),
        "avg_duration": round(df["duration"].mean(), 1),
        "top_trees": top_trees,
        "top_channels": top_channels,
        "duration_distribution": duration_dist,
        "hourly_distribution": hourly_dist,
        "weekly_trend": weekly_trend,
        "avg_retention": retention_summary,
    }

    print(f"📊 Global metrics computed")
    print(f"   Total sessions (all entities): {global_doc['total_sessions']}")
    print(f"   Total users: {global_doc['total_users']} | Total channels: {global_doc['total_channels']}")
    print(f"   Total focus time: {global_doc['total_focus_hours']} hours")
    print(f"   DAU: {last_1d} | WAU: {last_7d} | MAU: {last_30d}")

    return global_doc


# ══════════════════════════════════════════════════════════════════════════
#  STAGE 5 — VISUALIZATIONS
# ══════════════════════════════════════════════════════════════════════════

def generate_charts(df: pd.DataFrame, user_metrics: pd.DataFrame, global_doc: dict):
    """Generate analytics charts."""
    print("\n" + "═" * 60)
    print("  STAGE 5: VISUALIZATIONS")
    print("═" * 60)

    sns.set_theme(style="darkgrid", palette="viridis")

    # 1. Top Trees bar chart
    top_trees_df = df["tree"].value_counts().head(15)
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = sns.color_palette("viridis", len(top_trees_df))
    ax.barh(top_trees_df.index[::-1], top_trees_df.values[::-1], color=colors)
    ax.set_xlabel("Number of Sessions", fontsize=12)
    ax.set_title("Top 15 Most Planted Trees (All Time)", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "top_trees.png"), dpi=150)
    plt.close(fig)
    print("📊 top_trees.png saved")

    # 2. Sessions by Hour of Day (GMT+3)
    fig, ax = plt.subplots(figsize=(10, 5))
    hourly = df["hour"].value_counts().sort_index()
    ax.bar(hourly.index, hourly.values, color=sns.color_palette("coolwarm", 24), edgecolor="white")
    ax.set_xlabel("Hour of Day (GMT+3)", fontsize=12)
    ax.set_ylabel("Sessions", fontsize=12)
    ax.set_title("Focus Sessions by Hour of Day (GMT+3)", fontsize=14, fontweight="bold")
    ax.set_xticks(range(24))
    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "sessions_by_hour.png"), dpi=150)
    plt.close(fig)
    print("📊 sessions_by_hour.png saved")

    # 3. Sessions by Day of Week
    fig, ax = plt.subplots(figsize=(8, 5))
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow = df["day_of_week"].value_counts().sort_index()
    ax.bar([day_names[i] for i in dow.index], dow.values, color=sns.color_palette("Set2", 7), edgecolor="white")
    ax.set_xlabel("Day of Week", fontsize=12)
    ax.set_ylabel("Sessions", fontsize=12)
    ax.set_title("Focus Sessions by Day of Week", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "sessions_by_day.png"), dpi=150)
    plt.close(fig)
    print("📊 sessions_by_day.png saved")

    # 4. Duration Distribution
    fig, ax = plt.subplots(figsize=(10, 5))
    dur = df["duration"].value_counts().sort_index()
    ax.bar(dur.index.astype(str), dur.values, color="#4ECDC4", edgecolor="white")
    ax.set_xlabel("Duration (minutes)", fontsize=12)
    ax.set_ylabel("Sessions", fontsize=12)
    ax.set_title("Session Duration Distribution", fontsize=14, fontweight="bold")
    plt.xticks(rotation=45)
    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "duration_distribution.png"), dpi=150)
    plt.close(fig)
    print("📊 duration_distribution.png saved")

    # 5. Weekly Session Trend
    fig, ax = plt.subplots(figsize=(12, 5))
    weekly = global_doc["weekly_trend"]
    weeks = [w["week"] for w in weekly]
    session_counts = [w["sessions"] for w in weekly]
    user_counts = [w["unique_users"] for w in weekly]
    ax.bar(weeks, session_counts, color="#6C5CE7", alpha=0.7, label="Sessions")
    ax2 = ax.twinx()
    ax2.plot(weeks, user_counts, color="#E17055", marker="o", linewidth=2, label="Unique Users")
    ax.set_xlabel("Week", fontsize=12)
    ax.set_ylabel("Sessions", fontsize=12, color="#6C5CE7")
    ax2.set_ylabel("Unique Users", fontsize=12, color="#E17055")
    ax.set_title("Weekly Engagement Trend (Last 12 Weeks)", fontsize=14, fontweight="bold")
    plt.xticks(rotation=45)
    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "weekly_trend.png"), dpi=150)
    plt.close(fig)
    print("📊 weekly_trend.png saved")

    # 6. User Session Distribution (how many sessions per user)
    fig, ax = plt.subplots(figsize=(10, 5))
    session_counts_per_user = user_metrics["total_sessions"]
    bins = [1, 5, 10, 25, 50, 100, 250, 500, float("inf")]
    labels = ["1-4", "5-9", "10-24", "25-49", "50-99", "100-249", "250-499", "500+"]
    user_buckets = pd.cut(session_counts_per_user, bins=bins, labels=labels, right=False)
    bucket_counts = user_buckets.value_counts().reindex(labels)
    ax.bar(bucket_counts.index, bucket_counts.values, color=sns.color_palette("magma", len(labels)), edgecolor="white")
    ax.set_xlabel("Sessions per User", fontsize=12)
    ax.set_ylabel("Number of Users", fontsize=12)
    ax.set_title("User Engagement Distribution", fontsize=14, fontweight="bold")
    for i, (label, count) in enumerate(zip(bucket_counts.index, bucket_counts.values)):
        if count > 0:
            ax.text(i, count + 0.5, str(int(count)), ha="center", fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "user_distribution.png"), dpi=150)
    plt.close(fig)
    print("📊 user_distribution.png saved")


# ══════════════════════════════════════════════════════════════════════════
#  STAGE 6 — LOAD (Write to MongoDB)
# ══════════════════════════════════════════════════════════════════════════

async def load_to_mongodb(user_metrics_df: pd.DataFrame, global_doc: dict, retention: dict, channel_metrics_df: pd.DataFrame = None):
    """Write aggregated results to MongoDB."""
    print("\n" + "═" * 60)
    print("  STAGE 6: LOAD TO MONGODB")
    print("═" * 60)

    # User analytics — upsert each user
    if not user_metrics_df.empty:
        for _, row in user_metrics_df.iterrows():
            doc = row.to_dict()
            doc["updated_at"] = datetime.now(timezone.utc)
            await user_analytics.update_one(
                {"user_id": doc["user_id"]},
                {"$set": doc},
                upsert=True,
            )
        print(f"✅ Upserted {len(user_metrics_df)} user analytics documents")

    # Channel analytics — upsert each channel
    if channel_metrics_df is not None and not channel_metrics_df.empty:
        for _, row in channel_metrics_df.iterrows():
            doc = row.to_dict()
            doc["updated_at"] = datetime.now(timezone.utc)
            await channel_analytics.update_one(
                {"channel_id": doc["user_id"]},
                {"$set": doc},
                upsert=True,
            )
        print(f"✅ Upserted {len(channel_metrics_df)} channel analytics documents")

    # Global analytics — single document (replace)
    global_doc["retention_cohorts"] = retention
    await global_analytics.delete_many({})
    await global_analytics.insert_one(global_doc)
    print("✅ Wrote global analytics document")


# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser(description="BDA Pipeline — User Engagement Analytics")
    parser.add_argument("--dry", action="store_true", help="Analyze only, don't write to MongoDB")
    args = parser.parse_args()

    print("🚀 BDA Pipeline — User Engagement Analytics & Retention")
    print("=" * 60)

    # Stage 1: Extract & Transform
    df = await extract_sessions()
    if df.empty:
        print("❌ No data found. Exiting.")
        return

    user_df = df[df["entity_type"] == "user"].copy()
    channel_df = df[df["entity_type"] == "channel"].copy()

    # Stage 2: Per-user & per-channel metrics
    user_metrics_df = compute_user_metrics(user_df, label="USER")
    channel_metrics_df = compute_user_metrics(channel_df, label="CHANNEL")

    # Stage 3: Retention cohorts (evaluated on genuine user accounts)
    retention = compute_retention_cohorts(user_df)

    # Stage 4: Global metrics (evaluated on complete community dataset)
    global_doc = compute_global_metrics(df, user_metrics_df, retention, channel_metrics=channel_metrics_df)

    # Stage 5: Visualizations (generated on complete community dataset)
    generate_charts(df, user_metrics_df, global_doc)

    # Stage 6: Load to MongoDB
    if not args.dry:
        await load_to_mongodb(user_metrics_df, global_doc, retention, channel_metrics_df)
    else:
        print("\n⏭ Dry run — skipping MongoDB write")

    # Save CSVs for reference
    user_metrics_df.to_csv(os.path.join(OUTPUT_DIR, "user_metrics.csv"), index=False)
    channel_metrics_df.to_csv(os.path.join(OUTPUT_DIR, "channel_metrics.csv"), index=False)
    print(f"\n💾 User metrics CSV saved → {OUTPUT_DIR}/user_metrics.csv")
    print(f"💾 Channel metrics CSV saved → {OUTPUT_DIR}/channel_metrics.csv")

    print("\n" + "=" * 60)
    print(f"✅ BDA PIPELINE COMPLETE")
    print(f"   All charts saved to {OUTPUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
