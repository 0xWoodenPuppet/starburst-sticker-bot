import os
import xml.etree.ElementTree as ET
import csv
import re

# This regex matches the internal keys Forest uses for trees (e.g., tree_type_0_title)
REGEX_PATTERN = re.compile(r"tree_type_(\d+)_title")

def extract_all_languages(res_path):
    # Dictionary structure: { 'tree_type_0_title': { 'default': 'Cedar', 'fr': 'Cèdre', ... } }
    data = {}
    
    # Set to keep track of all found languages (e.g., 'fr', 'ja', 'zh-rTW')
    all_languages = set()
    all_languages.add('default') # English is usually in the default 'values' folder

    print(f"📂 Scanning folders in: {res_path}")

    # 1. Walk through every folder in the 'res' directory
    for folder in os.listdir(res_path):
        folder_path = os.path.join(res_path, folder)
        
        # We only care about folders starting with 'values'
        if os.path.isdir(folder_path) and folder.startswith("values"):
            
            # Determine the language code
            if folder == "values":
                lang_code = "default"
            else:
                # Extract code from 'values-fr', 'values-zh-rTW', etc.
                lang_code = folder.split("-", 1)[1]
            
            all_languages.add(lang_code)
            
            # 2. Parse the strings.xml file inside
            xml_file = os.path.join(folder_path, "strings.xml")
            if os.path.exists(xml_file):
                try:
                    tree = ET.parse(xml_file)
                    root = tree.getroot()
                    
                    for string_elem in root.findall('string'):
                        key = string_elem.get('name')
                        value = string_elem.text
                        
                        if key and value and REGEX_PATTERN.match(key):
                            if key not in data:
                                data[key] = {}
                            # Save the translation
                            data[key][lang_code] = value.strip()
                            
                except Exception as e:
                    print(f"⚠️ Could not parse {folder}: {e}")

    return data, sorted(list(all_languages))

def save_csv(data, languages):
    filename = "forest_master_list.csv"
    
    # Sort keys by the Tree ID number (0, 1, 2...) instead of alphabetically
    def get_id(k):
        return int(re.findall(r'\d+', k)[0])
    
    sorted_keys = sorted(data.keys(), key=get_id)

    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # Header: ID, Key, default, fr, ja, ...
        header = ['ID', 'Key'] + languages
        writer.writerow(header)
        
        count = 0
        for key in sorted_keys:
            tree_id = get_id(key)
            row = [tree_id, key]
            
            for lang in languages:
                # Get translation or empty string if missing
                row.append(data[key].get(lang, ""))
            
            writer.writerow(row)
            count += 1
            
    print(f"✅ Done! Extracted {count} trees across {len(languages)} languages.")
    print(f"💾 File saved as: {filename}")

if __name__ == "__main__":
    # Assumes you run this script INSIDE the folder containing 'res'
    res_dir = os.path.join(os.getcwd(), "res")
    
    if os.path.exists(res_dir):
        tree_data, lang_list = extract_all_languages(res_dir)
        save_csv(tree_data, lang_list)
    else:
        print("❌ Error: Could not find 'res' folder.")
        print("Make sure you are running this inside the decoded APK folder!")