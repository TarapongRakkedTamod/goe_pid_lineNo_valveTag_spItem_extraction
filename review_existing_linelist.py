import pandas as pd
import numpy as np
import re

def reconcile_line_lists(pid_csv_path, master_csv_path, output_csv_path):
    print("Loading datasets...")
    
    # 1. Load the data (Force utf-8 reading)
    pid_df = pd.read_csv(pid_csv_path, low_memory=False, encoding='utf-8')
    master_df = pd.read_csv(master_csv_path, low_memory=False, encoding='utf-8')

    # --- FIX ENCODING / GARBLED TEXT ---
    if 'OTC DOC. NO:' in pid_df.columns:
        pid_df['OTC DOC. NO:'] = pid_df['OTC DOC. NO:'].astype(str).str.replace('\u2011', '-', regex=False)
        pid_df['OTC DOC. NO:'] = pid_df['OTC DOC. NO:'].str.replace('â\x80\x91', '-', regex=False)
        
    pid_df['line_no'] = pid_df['line_no'].astype(str).str.replace('\u2011', '-', regex=False).str.strip()
    master_df['Line No'] = master_df['Line No'].astype(str).str.replace('\u2011', '-', regex=False).str.strip()

    # 2. Ensure necessary columns exist and are of 'object' type
    for col in ['TPR_comment', 'TPR_pid_no']:
        if col not in master_df.columns:
            master_df[col] = pd.Series(dtype='object')
        else:
            master_df[col] = master_df[col].astype('object')

    # --- NORMALIZATION (1-1/2, 1 1/2 -> 1.1/2) ---
    regex_pattern = r'(\d+)[\-\s]+(\d+/\d+)'
    pid_df['Norm_Line_No'] = pid_df['line_no'].str.replace(regex_pattern, r'\1.\2', regex=True)
    master_df['Norm_Line_No'] = master_df['Line No'].str.replace(regex_pattern, r'\1.\2', regex=True)

    # Rule 4: Handle duplicates in P&ID output by merging 'OTC DOC. NO:'
    print("Grouping and merging P&ID duplicates...")
    pid_grouped = pid_df.groupby(['line_no', 'Norm_Line_No'])['OTC DOC. NO:'].apply(
        lambda x: ', '.join(x.dropna().astype(str).unique())
    ).reset_index()

    # --- SEQUENCE EXTRACTOR ---
    def get_sequence_number(line_str):
        matches = re.findall(r'-(\d{3,5})(?:-|$)', line_str)
        if matches:
            return matches[-1]
        parts = line_str.split('-')
        return parts[-1] if len(parts) > 0 else line_str

    master_df['Seq_No'] = master_df['Norm_Line_No'].apply(get_sequence_number)

    touched_master_indices = set()
    unmatched_pid_rows = []

    print("Reconciling lines...")
    
    # ==========================================
    # PASS 1: Exact Matches Only
    # ==========================================
    for _, row in pid_grouped.iterrows():
        pid_line_orig = row['line_no']
        pid_norm = row['Norm_Line_No']
        pid_doc_merged = row['OTC DOC. NO:']

        if pid_line_orig.lower() == 'nan' or pid_line_orig == '':
            continue

        # Find exact matches that haven't been touched yet
        exact_match_indices = master_df.index[
            (master_df['Norm_Line_No'] == pid_norm) & 
            (~master_df.index.isin(touched_master_indices))
        ].tolist()
        
        if exact_match_indices:
            idx = exact_match_indices[0] # Claim the first available exact match
            master_df.at[idx, 'TPR_comment'] = 'matched'
            master_df.at[idx, 'TPR_pid_no'] = pid_doc_merged
            touched_master_indices.add(idx)
        else:
            # Save for Pass 2
            unmatched_pid_rows.append(row)

    # ==========================================
    # PASS 2: Optimal Partial Matches (Highest Score Wins)
    # ==========================================
    still_unmatched_pid_rows = []
    
    # Group the remaining P&ID lines by Sequence Number
    pid_unmatched_by_seq = {}
    for row in unmatched_pid_rows:
        seq = get_sequence_number(row['Norm_Line_No'])
        if seq not in pid_unmatched_by_seq:
            pid_unmatched_by_seq[seq] = []
        pid_unmatched_by_seq[seq].append(row)

    for seq, pid_rows in pid_unmatched_by_seq.items():
        # Find all available Master lines for this sequence
        available_master_indices = master_df.index[
            (master_df['Seq_No'] == seq) & 
            (~master_df.index.isin(touched_master_indices))
        ].tolist()

        if not available_master_indices:
            still_unmatched_pid_rows.extend(pid_rows)
            continue

        # Calculate scores for ALL possible pairs (P&ID line vs Master line)
        pair_scores = []
        for pid_idx_in_list, p_row in enumerate(pid_rows):
            pid_norm = p_row['Norm_Line_No']
            pid_parts = pid_norm.split('-')
            
            for m_idx in available_master_indices:
                master_norm = master_df.at[m_idx, 'Norm_Line_No']
                master_parts = master_norm.split('-')
                
                mismatches = []
                mismatch_score = 0
                
                if len(pid_parts) != len(master_parts):
                    mismatches.append(f"Format mismatch: P&ID has {len(pid_parts)} parts, Master has {len(master_parts)}")
                    mismatch_score += abs(len(pid_parts) - len(master_parts)) * 10
                
                for i, (p, m) in enumerate(zip(pid_parts, master_parts)):
                    if p != m:
                        mismatches.append(f"Part {i+1} [P&ID: '{p}' vs Master: '{m}']")
                        mismatch_score += 1
                        
                pair_scores.append((mismatch_score, pid_idx_in_list, m_idx, mismatches))

        # Sort pairs by best score (lowest mismatch count)
        pair_scores.sort(key=lambda x: x[0])

        assigned_pids = set()
        assigned_masters = set()

        # Assign the best pairs first!
        for score, pid_idx_in_list, m_idx, mismatches in pair_scores:
            if pid_idx_in_list not in assigned_pids and m_idx not in assigned_masters:
                # Lock in the optimal match
                assigned_pids.add(pid_idx_in_list)
                assigned_masters.add(m_idx)
                
                best_comment = "Partial match - Differences: " + ", ".join(mismatches)
                master_df.at[m_idx, 'TPR_comment'] = best_comment
                master_df.at[m_idx, 'TPR_pid_no'] = pid_rows[pid_idx_in_list]['OTC DOC. NO:']
                touched_master_indices.add(m_idx)

        # Any P&ID line that lost out on pairing goes to Pass 3
        for pid_idx_in_list, p_row in enumerate(pid_rows):
            if pid_idx_in_list not in assigned_pids:
                still_unmatched_pid_rows.append(p_row)

    # ==========================================
    # PASS 3: New Lines Addition
    # ==========================================
    new_rows = []
    for row in still_unmatched_pid_rows:
        new_row = {col: np.nan for col in master_df.columns}
        new_row['Line No'] = row['line_no'] 
        new_row['TPR_pid_no'] = row['OTC DOC. NO:']
        new_row['TPR_comment'] = 'New line added from latest P&ID'
        new_rows.append(new_row)

    # ==========================================
    # Condition D: Flag completely Unmatched Master Lines
    # ==========================================
    print("Flagging unmatched lines...")
    unmatched_mask = (~master_df.index.isin(touched_master_indices)) & (master_df['TPR_comment'].isna() | (master_df['TPR_comment'] == ''))
    master_df.loc[unmatched_mask, 'TPR_comment'] = 'Unmatched - Not found in latest P&ID'

    # Append newly found lines
    if new_rows:
        print(f"Adding {len(new_rows)} new lines to Master List...")
        new_df = pd.DataFrame(new_rows)
        new_df = new_df.dropna(axis=1, how='all')
        master_df = pd.concat([master_df, new_df], ignore_index=True)

    # Cleanup
    master_df.drop(columns=['Seq_No', 'Norm_Line_No'], inplace=True, errors='ignore')

    # Save
    master_df.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
    print(f"Success! Updated Master Line List saved to '{output_csv_path}'.")

# ==========================================
# Run the script
# ==========================================
if __name__ == "__main__":
    PID_EXTRACTION_FILE = "PID_line_list.csv"
    MASTER_CSV_FILE = "ISO_line_list.csv"
    OUTPUT_FILE = "Updated_Master_Line_List.csv"
    
    reconcile_line_lists(PID_EXTRACTION_FILE, MASTER_CSV_FILE, OUTPUT_FILE)