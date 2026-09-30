import os
import re
import logging
import joblib

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "nlp_output",
    "models",
    "nlp_toxicity_pipeline.joblib"
)

_cached_pipeline = None


def get_pipeline():
    """Lazily loads and caches the pre-trained NLP pipeline artifact."""
    global _cached_pipeline
    if _cached_pipeline is None:
        if not os.path.exists(MODEL_PATH):
            logger.error(f"NLP model artifact not found at: {MODEL_PATH}")
            return None
        try:
            _cached_pipeline = joblib.load(MODEL_PATH)
            logger.info("Successfully loaded NLP toxicity pipeline into memory.")
        except Exception as e:
            logger.error(f"Failed to load NLP pipeline artifact: {e}")
            return None
    return _cached_pipeline


def reload_pipeline():
    """Hot-reloads the cached pipeline artifact from disk."""
    global _cached_pipeline
    _cached_pipeline = None
    logger.info("Hot-reloading NLP toxicity pipeline from disk...")
    return get_pipeline()


def clean_text(text: str) -> str:
    """Canonical text preprocessor matching nlp_pipeline.py:
    - Normalizes URLs, mentions, and currency/numbers
    - Cleans punctuation and whitespace
    - Lowercases text
    """
    if not isinstance(text, str):
        return ""
    text = re.sub(r"https?://\S+|www\.\S+", " _URL_ ", text)
    text = re.sub(r"@\w+", " _MENTION_ ", text)
    text = re.sub(r"[\$£€]\s*\d+([.,]\d+)?", " _NUM_ ", text)
    text = re.sub(r"\b\d+\b", " _NUM_ ", text)
    text = re.sub(r"([!?,.]){2,}", r" \1 ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _extract_active_ngrams(cleaned_text: str, pipeline) -> list[str]:
    """Identifies the most influential active n-grams present in the text, ranked by severity."""
    try:
        clf = pipeline.named_steps["clf"]
        feature_union = pipeline.named_steps["features"]
        word_features = feature_union.transformer_list[0][1].get_feature_names_out()
        char_features = feature_union.transformer_list[1][1].get_feature_names_out()
        all_features = list(word_features) + list(char_features)
        coefs = clf.coef_[0]

        # Find positive (toxic) features that appear in the input string
        candidates = []
        for feat, coef in zip(all_features, coefs):
            if coef > 0.5 and feat in cleaned_text:
                clean_feat = feat.strip()
                if clean_feat and len(clean_feat) > 2:
                    candidates.append((clean_feat, float(coef)))

        # Sort descending by coefficient and deduplicate
        candidates.sort(key=lambda x: x[1], reverse=True)
        seen = set()
        matched = []
        for feat, _ in candidates:
            if feat not in seen:
                seen.add(feat)
                matched.append(feat)
            if len(matched) >= 5:
                break
        return matched
    except Exception:
        return []



async def classify_toxicity(text: str) -> dict:
    """Classifies message toxicity using the local trained NLP pipeline.

    Args:
        text (str): The raw message text to evaluate.

    Returns:
        dict: {
            "toxicity_score": float (0.0 - 1.0),
            "category": str ("safe", "spam_scam", "harassment_insult", "borderline"),
            "severity": str ("none", "low", "medium", "high"),
            "rule_broken": str,
            "detected_ngrams": list[str],
            "reason": str
        }
    """
    if not text or not text.strip():
        return {
            "toxicity_score": 0.0,
            "category": "safe",
            "severity": "none",
            "rule_broken": "None",
            "detected_ngrams": [],
            "reason": "Empty message."
        }

    pipeline = get_pipeline()
    if pipeline is None:
        logger.warning("NLP pipeline not available, returning safe fallback.")
        return {
            "toxicity_score": 0.0,
            "category": "unknown",
            "severity": "none",
            "rule_broken": "None",
            "detected_ngrams": [],
            "reason": "Model artifact unavailable."
        }

    cleaned = clean_text(text)
    try:
        # Class probabilities: index 0 = safe, index 1 = toxic/violation
        probs = pipeline.predict_proba([cleaned])[0]
        toxic_score = float(probs[1])
        toxic_score = round(max(0.0, min(1.0, toxic_score)), 3)

        detected_ngrams = _extract_active_ngrams(cleaned, pipeline)

        # Categorize output
        if toxic_score >= 0.80:
            severity = "high"
            if any(term in cleaned for term in ["bitcoin", "crypto", "cash", "giveaway", "_url_", "invest", "bonus", "airdrop"]):
                category = "spam_scam"
                rule_broken = "Rule 2: No spam, scams, or self-promotion."
                reason = f"High-confidence scam/spam detection (score: {toxic_score})."
            else:
                category = "harassment_insult"
                rule_broken = "Rule 3: No disrespectful behavior or insults."
                reason = f"High-confidence abusive content detected (score: {toxic_score})."
        elif toxic_score >= 0.50:
            severity = "medium"
            category = "borderline"
            rule_broken = "Potentially disrespectful or off-topic."
            reason = f"Moderate toxicity/spam likelihood (score: {toxic_score})."
        elif toxic_score >= 0.25:
            severity = "low"
            category = "borderline"
            rule_broken = "None"
            reason = f"Low risk / mild phrasing (score: {toxic_score})."
        else:
            severity = "none"
            category = "safe"
            rule_broken = "None"
            reason = "Content complies with community standards."

        return {
            "toxicity_score": toxic_score,
            "category": category,
            "severity": severity,
            "rule_broken": rule_broken,
            "detected_ngrams": detected_ngrams,
            "reason": reason
        }

    except Exception as e:
        logger.error(f"Error during local NLP classification: {e}")
        return {
            "toxicity_score": 0.0,
            "category": "unknown",
            "severity": "none",
            "rule_broken": "None",
            "detected_ngrams": [],
            "reason": f"Inference error: {e}"
        }


if __name__ == "__main__":
    import asyncio
    import json

    test_samples = [
        "Hey everyone! Starting a 45 min focus session on Calculus.",
        "Join my room here: https://forestapp.cc/join-room?token=3K7MQGESG",
        "Shut up you absolute idiot, you are completely useless and nobody likes you.",
        "FREE BITCOIN GIVEAWAY! CLICK HERE NOW TO DOUBLE YOUR MONEY: https://scam-crypto.xyz",
        "Invest $100 in my crypto bot and make $2,000 guaranteed profit!",
        "Thanks for planting with me today, great study sprint!"
    ]

    async def run_tests():
        print("--- Testing Local NLP Toxicity Classifier ---")
        for sample in test_samples:
            res = await classify_toxicity(sample)
            print(f"\nText: \"{sample}\"")
            print(f"Result: {json.dumps(res, indent=2)}")

    asyncio.run(run_tests())
