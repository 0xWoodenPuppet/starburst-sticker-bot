import asyncio
from db import sessions
from config import SESSION_USERS

# Invert SESSION_USERS to map channel_id -> user_id
CHANNEL_TO_USER = {v: str(k) for k, v in SESSION_USERS.items()}

async def audit_dataset():
    print("=== DATASET CLEANING & COUNT AUDIT ===")
    total = await sessions.count_documents({})
    print(f"1. Total Raw MongoDB Sessions: {total}")

    rows = []
    async for s in sessions.find({}):
        created_at = s.get("created_at")
        duration = s.get("duration", 0)
        host_id = s.get("host_id")

        if not created_at or duration <= 0:
            continue

        # Convert host_id to int or str
        host_str = str(host_id)
        
        # Map channel ID to user ID if in SESSION_USERS mapping
        if host_id in CHANNEL_TO_USER:
            mapped_user = CHANNEL_TO_USER[host_id]
        elif isinstance(host_id, int) and host_id < 0 and str(host_id) in CHANNEL_TO_USER:
            mapped_user = CHANNEL_TO_USER[str(host_id)]
        else:
            mapped_user = host_str

        # Minute-rounded timestamp for deduplication
        ts_min = created_at.strftime("%Y-%m-%d_%H:%M")

        rows.append({
            "id": str(s["_id"]),
            "raw_host_id": host_str,
            "mapped_user_id": mapped_user,
            "duration": duration,
            "ts_min": ts_min,
            "is_channel": 1 if (isinstance(host_id, int) and host_id < 0) or (isinstance(host_id, str) and host_id.startswith("-")) else 0
        })

    import pandas as pd
    df = pd.DataFrame(rows)
    print(f"\n2. Valid rows (duration > 0 and valid created_at): {len(df)}")

    # Channel vs User split
    channels_df = df[df["is_channel"] == 1]
    users_df = df[df["is_channel"] == 0]
    print(f"   - User hosted sessions (host_id > 0): {len(users_df)}")
    print(f"   - Channel hosted sessions (host_id < 0): {len(channels_df)}")

    # Mapped channels
    mapped_count = df[df["raw_host_id"] != df["mapped_user_id"]]
    print(f"   - Channel sessions successfully mapped to User IDs: {len(mapped_count)}")

    # Deduplication check
    df_dedup = df.drop_duplicates(subset=["mapped_user_id", "duration", "ts_min"])
    print(f"\n3. After Deduplicating Shared Links: {len(df_dedup)}")

    # If we filter out remaining unmapped channel IDs
    df_users_only = df_dedup[~df_dedup["mapped_user_id"].str.startswith("-")]
    print(f"\n4. Final Clean User-Only Dataset (Removing unmapped channels): {len(df_users_only)}")

    # Duration distribution
    print("\n=== DURATION DISTRIBUTION (User-Only Dataset) ===")
    print(df_users_only["duration"].value_counts().head(10))

if __name__ == "__main__":
    asyncio.run(audit_dataset())
