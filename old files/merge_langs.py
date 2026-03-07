import csv
import re

# Config: Columns to IGNORE (Android system folders)
# We filter these out to keep your final file clean.
IGNORE_PATTERNS = [
    r"\d+dp",   # w600dp, h720dp
    r"v\d+",    # v21, v31
    r"night",   # night mode
    r"land",    # landscape
    r"port",    # portrait
    r"watch",   # watch os
    r"dpi",     # hdpi, xhdpi
]

def is_junk_column(col_name):
    for pattern in IGNORE_PATTERNS:
        if re.search(pattern, col_name):
            return True
    return False

def load_stickers_map(sticker_file):
    """
    Loads your current stickers.csv into a map.
    Key: English Tree Name (lowercase)
    Value: Sticker ID
    """
    sticker_map = {}
    try:
        with open(sticker_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if row and len(row) >= 2:
                    name = row[0].strip().lower()
                    sticker_id = row[1].strip()
                    sticker_map[name] = sticker_id
    except FileNotFoundError:
        print(f"❌ Error: Could not find '{sticker_file}'.")
        exit()
    return sticker_map

def merge_files(master_file, sticker_map):
    final_rows = []
    seen_triggers = set() # To avoid duplicates like "Cedar" appearing 10 times

    with open(master_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)
        
        # 1. Map English Name -> Sticker ID
        # In your file, 'default' (English) is usually column 18, but let's find it dynamically
        try:
            default_idx = headers.index('default')
        except ValueError:
            print("❌ Error: Could not find 'default' column in master list.")
            exit()

        print(f"🔹 Processing {len(headers)} columns...")

        for row in reader:
            # Get the English name for this row (e.g., "Cedar")
            # .strip('"') removes the extra quotes around the name
            english_name = row[default_idx].strip().strip('"').lower()      
            
            # 2. Find the matching Sticker ID
            if english_name in sticker_map:
                sticker_id = sticker_map[english_name]
                
                # 3. Iterate through ALL columns in this row
                for i, cell_value in enumerate(row):
                    col_name = headers[i]
                    
                    # Skip ID, Key, and Junk columns
                    if col_name in ['ID', 'Key'] or is_junk_column(col_name):
                        continue
                    
                    # .strip('"') removes the quote marks from the start and end
                    trigger_word = cell_value.strip().strip('"').lower()
                    
                    # Only add if it has text and we haven't seen this exact trigger pair yet
                    if trigger_word and trigger_word not in seen_triggers:
                        final_rows.append([trigger_word, sticker_id])
                        seen_triggers.add(trigger_word)
            else:
                # Optional: Print trees you have NO sticker for
                # print(f"⚠️ Skipping '{english_name}' (No sticker found)")
                pass

    return final_rows

if __name__ == "__main__":
    print("🚀 Starting Merge...")
    
    # Load IDs
    st_map = load_stickers_map("stickers.csv")
    print(f"✅ Loaded {len(st_map)} sticker IDs.")
    
    # Merge
    multilingual_data = merge_files("forest_master_list.csv", st_map)
    
    # Save
    output_file = "stickers_final.csv"
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(multilingual_data)
        
    print(f"🎉 SUCCESS! Created '{output_file}' with {len(multilingual_data)} total triggers.")
    print("👉 Rename this file to 'stickers.csv' and upload it to GitHub!") 