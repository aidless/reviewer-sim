import pandas as pd
import os
import glob
from datetime import datetime

REPORTS_DIR = "outputs/reports"

# The column to group by
KEY_COLUMN = "paper_filename"
# The column to check for conflicts
CONFLICT_COLUMN = "recommendation" 

def find_discrepancies(run_dir: str = None):
    """
    Finds and reports on papers with conflicting recommendations
    across multiple consolidated report files.
    """
    print("--- Starting Report Comparison ---")
    
    # Use custom directories if provided
    if run_dir:
        reports_dir = os.path.join(run_dir, "outputs", "reports")
    else:
        reports_dir = REPORTS_DIR
    
    # 1. Find all consolidated report files
    report_files = glob.glob(os.path.join(reports_dir, "consolidated_reviews_*.csv"))
    
    if len(report_files) < 2:
        print(f"Error: Found only {len(report_files)} report(s) in {reports_dir}.")
        print("Please run the review system at least twice with different")
        print("models to generate reports to compare.")
        return

    print(f"Found {len(report_files)} reports to compare.")
    
    # 2. Load and combine all reports into one DataFrame
    all_dfs = []
    for f in report_files:
        try:
            df = pd.read_csv(f)
            # Add a 'source_report' column to track where the data came from
            df['source_report'] = os.path.basename(f)
            all_dfs.append(df)
        except Exception as e:
            print(f"Warning: Could not read file {f}. Error: {e}")
            
    if not all_dfs:
        print("Error: No valid report files could be loaded.")
        return

    master_df = pd.concat(all_dfs, ignore_index=True)
    
    # --- NEW STEP 2.5: Deduplicate the master DataFrame ---
    print(f"[Info] Original total rows loaded: {len(master_df)}")
    
    # Define the columns that make a row unique (as requested)
    dedupe_cols = [
        'paper_filename', 
        'extractor_model_used', 
        'synthesizer_model_used', 
        'overall_score'
    ]
    
    # Drop duplicates, keeping the first occurrence
    master_df = master_df.drop_duplicates(subset=dedupe_cols, keep='first')
    
    print(f"[Info] Rows after deduplication: {len(master_df)}")
    # --- END OF NEW STEP ---
    
    # 3. Find papers with conflicting recommendations
    print(f"Analyzing conflicts in '{CONFLICT_COLUMN}' grouped by '{KEY_COLUMN}'...")
    
    # Group by the paper and count unique recommendations
    grouped = master_df.groupby(KEY_COLUMN)[CONFLICT_COLUMN].nunique()
    
    # Filter to find papers where the count of unique recommendations is > 1
    conflicting_papers = grouped[grouped > 1].index
    
    if len(conflicting_papers) == 0:
        print("--- Comparison Complete ---")
        print("✅ No discrepancies found! All models produced the same recommendations.")
        return

    print(f"Found {len(conflicting_papers)} papers with conflicting recommendations.")
    
    # 4. Create the final discrepancy report
    # Filter the master DF to only include the papers with conflicts
    human_review_df = master_df[master_df[KEY_COLUMN].isin(conflicting_papers)]
    
    # Sort the report so conflicts are grouped together for easy reading
    human_review_df = human_review_df.sort_values(by=[
        KEY_COLUMN, 
        'extractor_model_used', 
        'synthesizer_model_used'
    ])
    
    # 5. Save the output file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = os.path.join(reports_dir, f"HUMAN_REVIEW_discrepancies_{timestamp}.csv")
    
    human_review_df.to_csv(output_path, index=False)
    
    print("--- Comparison Complete ---")
    print(f"✅ Success! Saved discrepancy report for human review to:")
    print(f"{output_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Compare reports with a specific directory")
    parser.add_argument("--run-dir", help="Directory for this run")
    args = parser.parse_args()
    
    find_discrepancies(args.run_dir)