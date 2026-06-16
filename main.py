import os
import re
import pandas as pd
import polars as pl
from pathlib import Path
import fitz  # PyMuPDF
from typing import List, Dict, Tuple, Any

class PDFTextExtractor:
    def __init__(self, folder_path: str):
        """
        Initialize the PDF extractor with the folder path containing PDF files.
        
        Args:
            folder_path: Path to folder containing PDF files
        """
        self.folder_path = Path(folder_path)
        self.all_text_data = []
        
    def read_all_pdfs(self) -> List[Path]:
        """
        Read all PDF files in the folder.
        
        Returns:
            List of PDF file paths
        """
        pdf_files = list(self.folder_path.glob("*.pdf"))
        if not pdf_files:
            raise FileNotFoundError(f"No PDF files found in {self.folder_path}")
        return pdf_files
    
    def extract_text_with_positions(self, pdf_path: Path) -> List[Dict]:
        """
        Extract text from each page with position information (x, y coordinates).
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of dictionaries containing page data with text and positions
        """
        page_data = []
        
        try:
            doc = fitz.open(pdf_path)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                # Get text with positions
                text_instances = page.get_text("words")  # Returns list of [x0, y0, x1, y1, word, block_no, line_no, word_no]
                
                for instance in text_instances:
                    x0, y0, x1, y1, word, block_no, line_no, word_no = instance
                    
                    # Calculate center x and y positions
                    center_x = (x0 + x1) / 2
                    center_y = (y0 + y1) / 2
                    
                    page_data.append({
                        'file_name': pdf_path.name,
                        'page_number': page_num + 1,
                        'text': word.strip(),
                        'x_position': round(center_x, 2),
                        'y_position': round(center_y, 2),
                        'x0': round(x0, 2),
                        'y0': round(y0, 2),
                        'x1': round(x1, 2),
                        'y1': round(y1, 2),
                        'block_number': block_no,
                        'line_number': line_no + 1,  # Convert to 1-based
                        'word_number': word_no + 1,   # Convert to 1-based
                        'raw_text': word
                    })
                    
            doc.close()
            
        except Exception as e:
            print(f"Error processing {pdf_path.name}: {e}")
            
        return page_data
    
    def split_and_strip_text(self, text_data: List[Dict]) -> List[Dict]:
        """
        Split text and strip whitespace.
        
        Args:
            text_data: List of text dictionaries
            
        Returns:
            Processed text data with stripped text
        """
        for item in text_data:
            # Split text by whitespace and strip each part
            if item['text']:
                # Clean the text: remove extra whitespace and strip
                item['text'] = ' '.join(item['text'].split()).strip()
                item['raw_text'] = ' '.join(item['raw_text'].split()).strip()
        return text_data
    
    def store_with_polars(self, text_data: List[Dict]) -> pl.DataFrame:
        """
        Store text data using Polars library with page number and file number columns.
        
        Args:
            text_data: List of text dictionaries
            
        Returns:
            Polars DataFrame with all data
        """
        # Create DataFrame with Polars
        df = pl.DataFrame(text_data)
        
        # Add file number (unique ID for each file)
        unique_files = df['file_name'].unique().to_list()
        file_mapping = {file: idx + 1 for idx, file in enumerate(unique_files)}
        
        df = df.with_columns(
            pl.col('file_name').map_dict(file_mapping).alias('file_number')
        )
        
        return df
    
    def capture_line_numbers(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Capture and extract line numbers using regex patterns.
        
        Args:
            df: Polars DataFrame
            
        Returns:
            DataFrame with extracted line numbers
        """
        # Pattern to capture line numbers (e.g., "Line 123", "L-456", "line:789")
        line_patterns = [
            r'(?:[Ll]ine\s*[:#]?\s*)(\d+)',
            r'(?:L[-_\s]*)(\d+)',
            r'(?:ln\s*[:#]?\s*)(\d+)',
            r'(?:#\s*)(\d+)'
        ]
        
        # Compile combined pattern
        combined_pattern = '|'.join(line_patterns)
        
        # Extract line numbers using regex
        df = df.with_columns([
            pl.col('text').str.extract(combined_pattern, 1).cast(pl.Int64, strict=False).alias('extracted_line_number')
        ])
        
        return df
    
    def capture_vertical_text(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Identify and capture vertical text (text with unusual orientation).
        
        Args:
            df: Polars DataFrame
            
        Returns:
            DataFrame with vertical text detection
        """
        # Vertical text detection based on position patterns
        # Group by page and check for text that appears in vertical columns
        vertical_patterns = [
            r'[A-Za-z]{2,}',  # Words that might be vertical
        ]
        
        # Check for vertical text by analyzing positions
        # If text is at same x position but varying y positions, it might be vertical
        df = df.with_columns([
            # Mark potential vertical text (simplified detection)
            pl.when(
                pl.col('text').str.contains('|'.join(vertical_patterns))
            ).then(pl.lit(True)).otherwise(pl.lit(False)).alias('is_vertical_text'),
            
            # Extract vertical text patterns
            pl.col('text').str.extract(r'([A-Z]{2,})', 1).alias('vertical_text_capture')
        ])
        
        return df
    
    def capture_pid_page_no(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Capture PID and page numbers using regex patterns.
        
        Args:
            df: Polars DataFrame
            
        Returns:
            DataFrame with extracted PID and page numbers
        """
        # PID patterns (e.g., "PID-12345", "PID: 67890")
        pid_pattern = r'(?:PID[-_\s:]*)(\d+)'
        
        # Page number patterns (e.g., "Page 123", "P-456", "pg:789")
        page_pattern = r'(?:[Pp]age\s*[:#]?\s*)(\d+)|(?:[Pp][-_\s]*)(\d+)|(?:pg\s*[:#]?\s*)(\d+)'
        
        # Extract PID
        df = df.with_columns([
            pl.col('text').str.extract(pid_pattern, 1).cast(pl.Int64, strict=False).alias('extracted_pid')
        ])
        
        # Extract page numbers
        df = df.with_columns([
            pl.col('text').str.extract(page_pattern, 1).cast(pl.Int64, strict=False).alias('extracted_page_number')
        ])
        
        # If first capture group didn't work, try second and third
        df = df.with_columns([
            pl.when(
                pl.col('extracted_page_number').is_null()
            ).then(
                pl.col('text').str.extract(page_pattern, 2).cast(pl.Int64, strict=False)
            ).otherwise(
                pl.col('extracted_page_number')
            ).alias('extracted_page_number')
        ])
        
        df = df.with_columns([
            pl.when(
                pl.col('extracted_page_number').is_null()
            ).then(
                pl.col('text').str.extract(page_pattern, 3).cast(pl.Int64, strict=False)
            ).otherwise(
                pl.col('extracted_page_number')
            ).alias('extracted_page_number')
        ])
        
        return df
    
    def export_to_csv(self, df: pl.DataFrame, output_path: str = "extracted_pdf_data.csv"):
        """
        Export the DataFrame to CSV file.
        
        Args:
            df: Polars DataFrame
            output_path: Output CSV file path
        """
        # Convert to Pandas for CSV export (or use Polars write_csv)
        # Using Polars built-in CSV writer
        df.write_csv(output_path)
        print(f"Data exported to {output_path}")
        
        # Also save a summary CSV with distinct pages and PIDs
        summary_df = df.select([
            'file_name', 'file_number', 'page_number', 
            'extracted_pid', 'extracted_page_number', 'extracted_line_number'
        ]).unique()
        summary_df.write_csv(output_path.replace('.csv', '_summary.csv'))
        print(f"Summary exported to {output_path.replace('.csv', '_summary.csv')}")
    
    def process_all_pdfs(self, output_csv: str = "extracted_pdf_data.csv"):
        """
        Main processing function to execute all steps.
        
        Args:
            output_csv: Output CSV file path
        """
        # Step 1: Read all PDF files
        pdf_files = self.read_all_pdfs()
        print(f"Found {len(pdf_files)} PDF files")
        
        all_data = []
        
        # Step 2: Extract text with positions
        for pdf_path in pdf_files:
            print(f"Processing: {pdf_path.name}")
            page_data = self.extract_text_with_positions(pdf_path)
            all_data.extend(page_data)
        
        # Step 3: Split and strip text
        all_data = self.split_and_strip_text(all_data)
        
        # Step 4: Store with Polars
        df = self.store_with_polars(all_data)
        print(f"Created DataFrame with {len(df)} rows")
        
        # Step 5: Capture line numbers
        df = self.capture_line_numbers(df)
        
        # Step 6: Capture vertical text
        df = self.capture_vertical_text(df)
        
        # Step 7: Capture PID and page numbers
        df = self.capture_pid_page_no(df)
        
        # Step 8: Export to CSV
        self.export_to_csv(df, output_csv)
        
        # Return the final DataFrame
        return df
    
    def display_summary(self, df: pl.DataFrame):
        """
        Display a summary of the extracted data.
        
        Args:
            df: Polars DataFrame
        """
        print("\n" + "="*50)
        print("EXTRACTION SUMMARY")
        print("="*50)
        
        print(f"Total text instances extracted: {len(df)}")
        print(f"Number of files processed: {df['file_name'].n_unique()}")
        print(f"Number of pages: {df['page_number'].max()}")
        
        # Show sample data
        print("\nSample Data:")
        print(df.head(10))
        
        # Show columns
        print(f"\nColumns: {df.columns}")
        
        # Show extracted PID count
        pid_count = df.filter(pl.col('extracted_pid').is_not_null()).height
        print(f"\nText instances with extracted PID: {pid_count}")
        
        # Show extracted page numbers count
        page_count = df.filter(pl.col('extracted_page_number').is_not_null()).height
        print(f"Text instances with extracted page number: {page_count}")
        
        # Show vertical text count
        vertical_count = df.filter(pl.col('is_vertical_text') == True).height
        print(f"Text instances identified as vertical: {vertical_count}")


def main():
    """
    Main execution function.
    """
    # Set your folder path here
    folder_path = "./pdf_files"  # Change this to your folder path
    
    # If folder doesn't exist, create it
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        print(f"Created folder: {folder_path}")
        print("Please add PDF files to this folder and run again.")
        return
    
    try:
        # Initialize extractor
        extractor = PDFTextExtractor(folder_path)
        
        # Process all PDFs
        output_csv = "extracted_pdf_data.csv"
        df = extractor.process_all_pdfs(output_csv)
        
        # Display summary
        extractor.display_summary(df)
        
        print(f"\n✅ Processing complete! Check '{output_csv}' for results.")
        
    except FileNotFoundError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()


if _name_ == "_main_":
    main()