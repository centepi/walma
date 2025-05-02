import json
import re
import os
import sys

# Function to clean math formatting
def clean_math_format(json_data):
    def clean_string(s):
        # Remove block math wrappers like $$...$$ or \\[...\\]
        s = re.sub(r'\$\$(.*?)\$\$', r'\1', s, flags=re.DOTALL)
        s = re.sub(r'\\\[(.*?)\\\]', r'\1', s, flags=re.DOTALL)
        # Remove inline math wrappers like $...$ or \\(...\\)
        s = re.sub(r'(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)', r'\1', s, flags=re.DOTALL)
        s = re.sub(r'\\\((.*?)\\\)', r'\1', s, flags=re.DOTALL)
        return s

    if isinstance(json_data, dict):
        for key, value in json_data.items():
            json_data[key] = clean_math_format(value)
    elif isinstance(json_data, list):
        json_data = [clean_math_format(item) for item in json_data]
    elif isinstance(json_data, str):
        json_data = clean_string(json_data)

    return json_data

# Go through each JSON file and clean it
def clean_all_json_files(folder_path):
    for filename in os.listdir(folder_path):
        if filename.endswith(".json"):
            file_path = os.path.join(folder_path, filename)
            with open(file_path, 'r') as infile:
                data = json.load(infile)

            cleaned_data = clean_math_format(data)

            with open(file_path, 'w') as outfile:
                json.dump(cleaned_data, outfile, indent=2)

            print(f"✅ Cleaned: {filename}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Please provide a folder path, e.g., python3 clean_math.py src/modules/calc2/week1/")
    else:
        folder = sys.argv[1]
        clean_all_json_files(folder)