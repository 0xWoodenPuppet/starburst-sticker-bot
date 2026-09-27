"""Tree name normalizer.

Maps multilingual Forest app tree names to a single canonical English name
using two CSV files:
  - stickers.csv: all tree name variants (multilingual) → sticker_id
  - _archive/stickers_english.csv: sticker_id → canonical English name

Usage:
    from services.tree_normalizer import normalize_tree, get_all_canonical_names

    normalize_tree("جاكاراندا")  # → "jacaranda"
    normalize_tree("Jacaranda")  # → "jacaranda"
    normalize_tree("unknown")    # → "unknown"
"""

import csv
import os

_BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
_STICKERS_PATH = os.path.join(_BASE_DIR, "stickers.csv")
_ENGLISH_PATH = os.path.join(_BASE_DIR, "_archive", "stickers_english.csv")

# ── Lookup tables (built once on import) ──────────────────────────────
# {tree_name_lowercase: canonical_english_name}
_NAME_TO_CANONICAL: dict[str, str] = {}
# {sticker_id: canonical_english_name}
_STICKER_TO_CANONICAL: dict[str, str] = {}


def _build_lookup():
    """Parse both CSV files and build the normalization lookup tables."""

    # Step 1: Load the English canonical name for each sticker_id
    with open(_ENGLISH_PATH, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) == 2:
                name = row[0].strip().lower()
                sticker_id = row[1].strip()
                _STICKER_TO_CANONICAL[sticker_id] = name

    # Step 2: Map every multilingual name variant to its canonical English name
    with open(_STICKERS_PATH, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) == 2:
                name = row[0].strip().lower()
                sticker_id = row[1].strip()
                canonical = _STICKER_TO_CANONICAL.get(sticker_id)
                if canonical:
                    _NAME_TO_CANONICAL[name] = canonical

    # Also map the English names themselves (from stickers_english.csv)
    for canonical in _STICKER_TO_CANONICAL.values():
        _NAME_TO_CANONICAL[canonical] = canonical


_build_lookup()


def normalize_tree(name: str) -> str:
    """Normalize a tree name (any language) to its canonical English name.

    Returns the original name lowercased if no match is found.
    """
    return _NAME_TO_CANONICAL.get(name.strip().lower(), name.strip().lower())


def get_sticker_canonical(sticker_id: str) -> str:
    """Get the canonical name for a sticker ID."""
    return _STICKER_TO_CANONICAL.get(sticker_id, "unknown")


def get_all_canonical_names() -> list[str]:
    """Return all unique canonical tree names (sorted)."""
    return sorted(set(_STICKER_TO_CANONICAL.values()))


# ── CLI test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Loaded {len(_STICKER_TO_CANONICAL)} tree types")
    print(f"Total name variants: {len(_NAME_TO_CANONICAL)}")
    print(f"\nCanonical names ({len(get_all_canonical_names())}):")
    for name in get_all_canonical_names():
        print(f"  🌳 {name.title()}")

    # Test some lookups
    test_cases = [
        "jacaranda", "جاكاراندا", "ジャカランダ",
        "cedar", "ارز", "삼나무",
        "wishing tree", "شجرة الأمنيات",
        "mock orange", "celindo", "سيكلامين",
        "unknown", "nonexistent tree",
    ]
    print(f"\nTest lookups:")
    for t in test_cases:
        print(f"  '{t}' → '{normalize_tree(t)}'")
