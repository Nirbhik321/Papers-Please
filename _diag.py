"""Show all rows for JAN 2025."""
import sys
sys.path.insert(0, ".")
from modules.detector import detect_and_extract

pdf_path = "data/raw/JAN 2025 BCS502.pdf"
_, rows = detect_and_extract(pdf_path)
print(f"{len(rows)} rows\n")
for i, row in enumerate(rows):
    print(f"  row{i:02d}: {row}")
