# intructions: 
# download latest forest apk
# use this command: apktool d forest-stay-focused.apk -o decoded-apk
# put the stickers_english.csv with the new trees in the decoded-apk 
# use this command: python decoded-apk
# A new csv will be created, copy and paste the output in stickers.csv


import os
import xml.etree.ElementTree as ET
import csv
import re
import argparse

# Matches Forest's internal key format: tree_type_0_title, tree_type_12_title, etc.
REGEX_PATTERN = re.compile(r"tree_type_(\d+)_title")

# Folders to skip — these aren't real language variants
IGNORE_PATTERNS = [
    r"\d+dp",   # w600dp, h720dp
    r"v\d+",    # v21, v31
    r"night",   # night mode
    r"land",    # landscape
    r"port",    # portrait
    r"watch",   # watch os
    r"dpi",     # hdpi, xhdpi
]

def is_junk_folder(folder_name):
    lang_part = folder_name.split("-", 1)[1] if "-" in folder_name else folder_name
    for pattern in IGNORE_PATTERNS:
        if re.search(pattern, lang_part):
            return True
    return False

def load_processed_ids(existing_db):
    """
    Reads your main multilingual database and returns the set of
    sticker IDs that already have entries — so we can skip them.
    """
    processed = set()
    try:
        with open(existing_db, 'r', encoding='utf-8') as f:
            for row in csv.reader(f):
                if row and len(row) >= 2:
                    processed.add(row[1].strip())
        print(f"📂 Main database: {len(processed)} sticker IDs already processed.")
    except FileNotFoundError:
        print(f"⚠️  Could not find '{existing_db}', treating all trees as new.")
    return processed


def load_stickers_map(sticker_file):
    """
    Loads your stickers_english.csv (new trees only).
    Format: english_name, sticker_id  (no header)
    """
    sticker_map = {}
    skipped = []
    try:
        with open(sticker_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if row and len(row) >= 2:
                    name = row[0].strip().lower()
                    sticker_id = row[1].strip()
                    if sticker_id:
                        sticker_map[name] = sticker_id
                    else:
                        skipped.append(name)
    except FileNotFoundError:
        print(f"❌ Could not find '{sticker_file}'")
        exit()
    if skipped:
        print(f"⚠️  Skipped {len(skipped)} row(s) with no sticker ID: {', '.join(skipped)}")
    return sticker_map

def pull_translations(res_path, target_names):
    """
    1. Finds the internal APK key for each English name  (e.g. "cedar" → "tree_type_0_title")
    2. Scans every language folder and collects all translations for those keys
    Returns: { english_name → set of all trigger words across all languages }
    """

    # --- Step 1: Map English name → internal key via res/values/strings.xml ---
    english_xml = os.path.join(res_path, "values", "strings.xml")
    if not os.path.exists(english_xml):
        print(f"❌ Could not find '{english_xml}'. Make sure you're running this inside the decoded APK folder.")
        exit()

    key_to_name = {}  # e.g. "tree_type_0_title" → "cedar"
    tree = ET.parse(english_xml)
    for elem in tree.getroot().findall('string'):
        key = elem.get('name')
        value = elem.text
        if key and value and REGEX_PATTERN.match(key):
            name = value.strip().lower()
            if name in target_names:
                key_to_name[key] = name

    # Warn about any trees not found in the APK at all
    found_names = set(key_to_name.values())
    missing = target_names - found_names
    if missing:
        print(f"⚠️  These trees were NOT found in the APK's English strings: {', '.join(missing)}")

    if not key_to_name:
        print("❌ None of your target trees were found in the APK. Check spelling.")
        exit()

    # --- Step 2: Collect translations from every language folder ---
    results = {name: set() for name in found_names}
    lang_count = 0

    for folder in sorted(os.listdir(res_path)):
        folder_path = os.path.join(res_path, folder)

        if not os.path.isdir(folder_path) or not folder.startswith("values"):
            continue
        if is_junk_folder(folder):
            continue

        xml_file = os.path.join(folder_path, "strings.xml")
        if not os.path.exists(xml_file):
            continue

        lang_count += 1
        try:
            tree = ET.parse(xml_file)
            for elem in tree.getroot().findall('string'):
                key = elem.get('name')
                value = elem.text
                if key in key_to_name and value:
                    results[key_to_name[key]].add(value.strip().lower())
        except Exception as e:
            print(f"⚠️  Could not parse {folder}: {e}")

    print(f"🌐 Scanned {lang_count} language folders.")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pull all multilingual names for new trees directly from the APK's res/ folder."
    )
    parser.add_argument(
        '--stickers',
        default='stickers_english.csv',
        help='Your new-trees CSV: english_name, sticker_id  (default: stickers_english.csv)'
    )
    parser.add_argument(
        '--res',
        default='res',
        help='Path to the APK res/ folder (default: ./res)'
    )
    parser.add_argument(
        '--output',
        default='stickers_new_only.csv',
        help='Output file to append to your main database (default: stickers_new_only.csv)'
    )
    parser.add_argument(
        '--existing',
        default=None,
        help='Your main multilingual database CSV — trees already here will be skipped (e.g. stickers.csv)'
    )
    args = parser.parse_args()

    print("🚀 Starting...\n")

    sticker_map = load_stickers_map(args.stickers)
    if not sticker_map:
        print("❌ No trees loaded. Check your stickers file.")
        exit()

    # Filter out trees already in the main database
    if args.existing:
        processed_ids = load_processed_ids(args.existing)
        before = len(sticker_map)
        sticker_map = {k: v for k, v in sticker_map.items() if v not in processed_ids}
        skipped = before - len(sticker_map)
        if skipped:
            print(f"⏭️  Skipping {skipped} tree(s) already in your database.")
        if not sticker_map:
            print("✅ Nothing new to process — your database is already up to date.")
            exit()

    print(f"\n✅ {len(sticker_map)} new tree(s) to process: {', '.join(sticker_map.keys())}\n")

    translations = pull_translations(args.res, set(sticker_map.keys()))

    # Build output: [trigger_word, sticker_id], deduped
    final_rows = []
    seen = set()
    for english_name, variants in translations.items():
        sticker_id = sticker_map[english_name]
        for word in sorted(variants):
            if word and word not in seen:
                final_rows.append([word, sticker_id])
                seen.add(word)

    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerows(final_rows)

    print(f"\n🎉 Done! '{args.output}' has {len(final_rows)} triggers across {len(sticker_map)} tree(s).")
    print("👉 Append this to your main stickers database.")
