import os
import re 
import pandas as pd
import polars as pl
from pathlib import Path
import fitz # PyMuPDF
from typing import List, Dict, Tuple, Any

class PDFTextExtractor:
    def __init__(self, folder_path: str):
        """
            Initial the PDF extractor with the folder path containing pdf files.        

        Args:
            folder_path = Path to folder containing pdf files.

        """
        self.folder_path = Path(folder_path)
        self.all_text_data = []

    def read_all_pdfs(self) -> List[Path]:
        """
            Read all PDF files in the folder. 

        Returns:
            List of the pdf paths
        """
        pdf_files = list(self.folder_path.glob("*.pdf"))

        if not pdf_files:
            raise FileNotFoundError(f"No pdf files found in the folder {self.folder_path}")
        return pdf_files
    
    def extract_text_with_positions(self, pdf_path: Path) -> List[Dict]:
        """
            Extract text form each page with position information (x, y coordinates).

        Arges:
            pdf_path : Path to pdf FileExistsError
        
        Return:
            List of dictionaries containing page data with text and position 
        """
        page_data = []

        try:
            doc = fitz.open(pdf_path)

            for page_num in range(len(doc)):
                page = doc[page_num]

                # get text with positions
                text_instances = page.get_text("words") # Return list of [x0, y0, x1, y1, word, block_no, line_no, word_no]

                for instance in text_instances:
                    x0, y0, x1, y1, word, block_no, line_no, word_no = instance

                    # Calculate center x and y positions
                    center_x = (x0 + x1) / 2
                    center_y = (y0 + y1) / 2

                    page.data.append({
                        'file_name' : pdf_path.name,
                        'page_number' : page_num + 1,
                        'text' : word.strip(),
                        'x_position' : round(center_x, 2),
                        'y_position' : round(center_y, 2),
                        'x0' : round(x0, 2),
                        'y0' : round(y0, 2),
                        'x1' : round(x1, 2),
                        'y1' : round(y1, 2),
                        'block_number': block_no,
                        'line_number' : line_no + 1,
                        'word_number' : word_no + 1,
                        'raw_text' : word
                    })

            doc.close()

        except Exception as e:
            print(f"Error processing {pdf_path.name}: {e}")

        return page_data
    


                    


