"""
cli.py
Command-line entry point for headless pipeline runs.

Usage:
  python cli.py --input data/raw/ --subject "Data Structures"
  python cli.py --input data/raw/2021_ds.pdf --force
"""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="ExamLens — Question Paper Analysis Pipeline")
    parser.add_argument("--input", "-i", required=True,
                        help="Path to a PDF file or a directory of PDFs")
    parser.add_argument("--subject", "-s", default=None,
                        help="Subject name override (auto-detected from filename if omitted)")
    parser.add_argument("--config", "-c", default="config.yaml",
                        help="Path to config.yaml (default: config.yaml)")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Force re-process even if output already exists")
    args = parser.parse_args()

    # Resolve input paths
    input_path = Path(args.input)
    if input_path.is_dir():
        pdf_paths = sorted(input_path.glob("*.pdf"))
    elif input_path.is_file() and input_path.suffix.lower() == ".pdf":
        pdf_paths = [input_path]
    else:
        print(f"Error: {args.input} is not a PDF or directory of PDFs")
        return

    if not pdf_paths:
        print(f"No PDFs found in {args.input}")
        return

    print(f"\nExamLens Pipeline")
    print(f"{'─' * 40}")
    print(f"Input:   {args.input}")
    print(f"PDFs:    {len(pdf_paths)} file(s)")
    print(f"Subject: {args.subject or 'auto-detect'}")
    print(f"Force:   {args.force}")
    print(f"{'─' * 40}\n")

    from pipeline import run
    result = run(
        pdf_paths=[str(p) for p in pdf_paths],
        subject=args.subject,
        config_path=args.config,
        force=args.force,
    )

    if "error" in result:
        print(f"\nError: {result['error']}")
        return

    print(f"\n{'─' * 40}")
    print(f"Done!")
    print(f"  Questions : {result['total_questions']}")
    print(f"  Topics    : {result['total_clusters']}")
    print(f"  Papers    : {result['papers_processed']}")
    print(f"  Bank CSV  : {result['bank_path']}")
    print(f"  Scatter   : {result['scatter_path']}")
    print(f"{'─' * 40}")
    print(f"\nLaunch UI: streamlit run app.py")


if __name__ == "__main__":
    main()