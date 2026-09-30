import logging
from datetime import datetime, timezone
from bson import ObjectId
from db import user_credibility, mod_reports

logger = logging.getLogger(__name__)

DEFAULT_CREDIBILITY = 0.50
MIN_CREDIBILITY = 0.10
MAX_CREDIBILITY = 1.00

WEIGHT_TOXICITY = 0.70
WEIGHT_CREDIBILITY = 0.30


async def get_user_credibility(user_id: int) -> float:
    """Retrieves the credibility score for a reporting user (default 0.50)."""
    try:
        doc = await user_credibility.find_one({"user_id": user_id})
        if doc and "credibility" in doc:
            return float(doc["credibility"])
        return DEFAULT_CREDIBILITY
    except Exception as e:
        logger.error(f"Error fetching credibility for user {user_id}: {e}")
        return DEFAULT_CREDIBILITY


async def update_user_credibility(user_id: int, is_correct: bool) -> tuple[float, float]:
    """Updates user credibility based on admin confirmation or rejection.

    Confirmed (+0.10) / Rejected (-0.15). Bounded within [0.10, 1.00].
    Returns (old_credibility, new_credibility).
    """
    old_cred = await get_user_credibility(user_id)
    delta = 0.10 if is_correct else -0.15
    new_cred = round(max(MIN_CREDIBILITY, min(MAX_CREDIBILITY, old_cred + delta)), 2)

    try:
        await user_credibility.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "credibility": new_cred,
                    "updated_at": datetime.now(timezone.utc)
                },
                "$inc": {
                    "total_reports": 1,
                    "confirmed_reports": 1 if is_correct else 0,
                    "false_reports": 0 if is_correct else 1
                }
            },
            upsert=True
        )
        logger.info(f"Updated credibility for user {user_id}: {old_cred} -> {new_cred}")
    except Exception as e:
        logger.error(f"Failed to update credibility for user {user_id}: {e}")

    return old_cred, new_cred


def compute_composite_score(toxicity_score: float, reporter_credibility: float) -> dict:
    """Calculates the weighted decision score combining NLP toxicity and reporter reliability.

    Formula:
        composite = 0.70 * toxicity_score + 0.30 * reporter_credibility

    Thresholds:
        >= 0.75: MUTE
        >= 0.50: FLAG
        < 0.50:  NONE
    """
    toxicity_score = max(0.0, min(1.0, float(toxicity_score)))
    reporter_credibility = max(0.0, min(1.0, float(reporter_credibility)))

    composite = round(
        (WEIGHT_TOXICITY * toxicity_score) + (WEIGHT_CREDIBILITY * reporter_credibility),
        3
    )

    if composite >= 0.75:
        action = "MUTE"
        rationale = f"High composite severity ({composite:.3f}) based on NLP toxicity ({toxicity_score:.2f}) and reporter trust ({reporter_credibility:.2f})."
    elif composite >= 0.50:
        action = "FLAG"
        rationale = f"Moderate composite score ({composite:.3f}). Message flagged for human moderator audit."
    else:
        action = "NONE"
        rationale = f"Low composite score ({composite:.3f}). Message does not breach automated intervention threshold."

    return {
        "composite_score": composite,
        "action": action,
        "rationale": rationale,
        "weights": {
            "toxicity_weight": WEIGHT_TOXICITY,
            "credibility_weight": WEIGHT_CREDIBILITY
        }
    }


async def save_mod_report(
    chat_id: int,
    message_id: int,
    offending_user_id: int,
    offending_user_name: str,
    reporter_id: int,
    reporter_name: str,
    message_text: str,
    nlp_result: dict,
    reporter_credibility: float,
    decision: dict
) -> str:
    """Inserts a structured moderation report into MongoDB and returns the string report_id."""
    doc = {
        "chat_id": chat_id,
        "message_id": message_id,
        "offending_user_id": offending_user_id,
        "offending_user_name": offending_user_name,
        "reporter_id": reporter_id,
        "reporter_name": reporter_name,
        "message_text": message_text,
        "toxicity_score": nlp_result.get("toxicity_score", 0.0),
        "nlp_category": nlp_result.get("category", "unknown"),
        "detected_ngrams": nlp_result.get("detected_ngrams", []),
        "reporter_credibility": reporter_credibility,
        "composite_score": decision.get("composite_score", 0.0),
        "action_taken": decision.get("action", "NONE"),
        "rationale": decision.get("rationale", ""),
        "admin_verdict": "PENDING",
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": datetime.now(timezone.utc)
    }

    try:
        res = await mod_reports.insert_one(doc)
        return str(res.inserted_id)
    except Exception as e:
        logger.error(f"Error persisting mod report to MongoDB: {e}")
        return ""


async def record_admin_verdict(report_id: str, admin_id: int, is_correct: bool) -> dict | None:
    """Records an admin verification verdict and adjusts the reporting user's credibility.

    Returns dict with resolution details, or None if report not found/already resolved.
    """
    if not report_id:
        return None

    try:
        obj_id = ObjectId(report_id)
    except Exception:
        logger.error(f"Invalid ObjectId format for report_id: {report_id}")
        return None

    try:
        report = await mod_reports.find_one({"_id": obj_id})
        if not report:
            logger.warning(f"Mod report {report_id} not found.")
            return None

        if report.get("admin_verdict") != "PENDING":
            return {
                "already_resolved": True,
                "current_verdict": report.get("admin_verdict")
            }

        verdict_str = "CONFIRMED" if is_correct else "REJECTED"
        reporter_id = report.get("reporter_id")

        old_cred, new_cred = await update_user_credibility(reporter_id, is_correct)

        await mod_reports.update_one(
            {"_id": obj_id},
            {
                "$set": {
                    "admin_verdict": verdict_str,
                    "reviewed_by": admin_id,
                    "reviewed_at": datetime.now(timezone.utc),
                    "reporter_updated_credibility": new_cred
                }
            }
        )

        return {
            "already_resolved": False,
            "report_id": report_id,
            "verdict": verdict_str,
            "reporter_id": reporter_id,
            "reporter_name": report.get("reporter_name", "Unknown"),
            "old_credibility": old_cred,
            "new_credibility": new_cred,
            "action_taken": report.get("action_taken", "NONE")
        }

    except Exception as e:
        logger.error(f"Error recording admin verdict for {report_id}: {e}")
        return None


if __name__ == "__main__":
    import asyncio

    async def run_tests():
        print("--- Testing Credibility Scoring Engine ---")

        # Test composite score logic
        # 1. High toxicity (0.95) with normal user (0.50) -> 0.70*0.95 + 0.30*0.50 = 0.815 -> MUTE
        mute_res = compute_composite_score(0.95, 0.50)
        print("\nTest 1 (High Toxicity + Normal Credibility):")
        print(f"  Score: {mute_res['composite_score']} | Action: {mute_res['action']}")
        assert mute_res["action"] == "MUTE"

        # 2. Borderline toxicity (0.55) with low credibility user (0.20) -> 0.70*0.55 + 0.30*0.20 = 0.445 -> NONE
        none_res = compute_composite_score(0.55, 0.20)
        print("\nTest 2 (Borderline Toxicity + Low Credibility):")
        print(f"  Score: {none_res['composite_score']} | Action: {none_res['action']}")
        assert none_res["action"] == "NONE"

        # 3. Borderline toxicity (0.55) with high credibility user (0.90) -> 0.70*0.55 + 0.30*0.90 = 0.655 -> FLAG
        flag_res = compute_composite_score(0.55, 0.90)
        print("\nTest 3 (Borderline Toxicity + High Credibility):")
        print(f"  Score: {flag_res['composite_score']} | Action: {flag_res['action']}")
        assert flag_res["action"] == "FLAG"

        # Test MongoDB persistence
        test_uid = 999999999
        cred = await get_user_credibility(test_uid)
        print(f"\nInitial credibility for user {test_uid}: {cred}")

        old_c, new_c = await update_user_credibility(test_uid, True)
        print(f"After confirmed report: {old_c} -> {new_c}")
        assert new_c == round(old_c + 0.10, 2)

        # Clean up test user
        await user_credibility.delete_one({"user_id": test_uid})
        print("Cleaned up test record. All assertion checks passed!")

    asyncio.run(run_tests())
