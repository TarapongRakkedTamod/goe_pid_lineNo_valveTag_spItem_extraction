import os
import re
import csv
import pymupdf  # PyMuPDF

def extract_pid_data(input_folder="input", lines_output="line_list.csv", valves_output="valve_list.csv"):
    # Ensure the input directory exists
    if not os.path.exists(input_folder):
        os.makedirs(input_folder)
        print(f"Created '{input_folder}' directory. Please put your PDF files there and run again.")
        return

    # Define a robust dash character class (matches regular hyphen, non-breaking hyphen, minus, en-dash)
    dash = r'[\-\u2011\u2212\u2013\u2014]'
    
    # REGEX PATTERNS
    
    # 1. Line Numbers Pattern
    # Matches variations like: 51-1/2"-WS-G13-7015, 51-1/2"-WS-G13-7015-PP, 51-1 1/2"-WS...
    line_no_regex = fr'\b\d{{2,3}}{dash}\d+(?:\s+\d+/\d+|/\d+)?["”]?(?:{dash})?[A-Z]+{dash}[A-Z0-9]+{dash}\d+(?:{dash}[A-Z]{{2,3}})?\b'
    line_no_pattern = re.compile(line_no_regex)
    
    # 2. Valve Numbers Pattern
    # Matches variations like: 51BFV7006, 51CHV7118, 51BAV7115, 98HV7113
    # Breakdown: 2 digits + 1-3 letters ending in V (Valve) + 3-4 sequence digits + Optional 1 letter suffix
    valve_no_regex = r'\b\d{2}[A-Z]{1,2}V\d{3,4}[A-Z]?\b'
    valve_no_pattern = re.compile(valve_no_regex)

    # 3. Document Metadata Patterns
    doc_no_pattern = re.compile(fr'SC\d+{dash}[A-Z0-9]+{dash}[A-Z]+{dash}[A-Z]+{dash}[A-Z]+{dash}PID{dash}\d+')
    sheet_pattern = re.compile(r'\b(\d+\s*of\s*\d+)\b', re.IGNORECASE)
    rev_pattern = re.compile(r'\bR\d{2}\b')

    line_results = []
    valve_results = []
    
    # Scan input folder for .pdf files (case-insensitive)
    for filename in os.listdir(input_folder):
        if not filename.lower().endswith('.pdf'):
            continue

        filepath = os.path.join(input_folder, filename)
        
        try:
            doc = pymupdf.open(filepath)
        except Exception as e:
            print(f"Error opening {filename}: {e}")
            continue

        for page_index in range(len(doc)):
            page = doc[page_index]
            text = page.get_text("text")
            page_no = page_index + 1

            # --- Extract Document Metadata ---
            doc_no_match = doc_no_pattern.search(text)
            doc_no = doc_no_match.group(0) if doc_no_match else "UNKNOWN"

            rev = "UNKNOWN"
            filename_rev_match = re.search(r'_(R\d{2})\.pdf$', filename, re.IGNORECASE)
            if filename_rev_match:
                rev = filename_rev_match.group(1).upper()
            else:
                revs = rev_pattern.findall(text)
                if revs:
                    rev = max(revs)

            sheet_match = sheet_pattern.search(text)
            sheet = sheet_match.group(1).replace(" ", " ") if sheet_match else f"{page_no} of {len(doc)}"

            # --- Extract and deduplicate Line Numbers ---
            raw_lines = line_no_pattern.findall(text)
            seen_lines = set()
            unique_lines = []
            for ln in raw_lines:
                if ln not in seen_lines:
                    seen_lines.add(ln)
                    unique_lines.append(ln)

            # --- Extract and deduplicate Valve Numbers ---
            raw_valves = valve_no_pattern.findall(text)
            seen_valves = set()
            unique_valves = []
            for vn in raw_valves:
                if vn not in seen_valves:
                    seen_valves.add(vn)
                    unique_valves.append(vn)

            # --- Append to Result Lists ---
            for line_no in unique_lines:
                line_results.append({
                    'file_name': filename,
                    'page_no': page_no,
                    'OTC DOC. NO:': doc_no,
                    'OTC REV.': rev,
                    'SHEET': sheet,
                    'line_no': line_no
                })

            for valve_no in unique_valves:
                valve_results.append({
                    'file_name': filename,
                    'page_no': page_no,
                    'OTC DOC. NO:': doc_no,
                    'OTC REV.': rev,
                    'SHEET': sheet,
                    'valve_no': valve_no
                })

        doc.close()

    # --- Write Results to CSV ---
    
    # 1. Write Line List
    if line_results:
        line_fieldnames = ['file_name', 'page_no', 'OTC DOC. NO:', 'OTC REV.', 'SHEET', 'line_no']
        with open(lines_output, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=line_fieldnames, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            for row in line_results:
                writer.writerow(row)
        print(f"Saved {len(line_results)} lines to '{lines_output}'.")
    else:
        print(f"No line numbers found.")

    # 2. Write Valve List
    if valve_results:
        valve_fieldnames = ['file_name', 'page_no', 'OTC DOC. NO:', 'OTC REV.', 'SHEET', 'valve_no']
        with open(valves_output, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=valve_fieldnames, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            for row in valve_results:
                writer.writerow(row)
        print(f"Saved {len(valve_results)} valves to '{valves_output}'.")
    else:
        print(f"No valve numbers found.")

if __name__ == "__main__":
    extract_pid_data()