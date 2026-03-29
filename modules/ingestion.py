"""
ingestion.py — F01 F02 F04
Handles PDF text extraction and OCR for scanned papers.
Auto-detects whether a PDF is native text or scanned.
"""

import io
from pathlib import Path

import cv2
import numpy as np
import pdfplumber
import pytesseract
from PIL import Image


def _preprocess_image(img_array: np.ndarray) -> np.ndarray:
    """
    OpenCV pre-processing chain for scanned pages:
    greyscale → Otsu binarise → deskew → denoise
    """
    # Greyscale
    if len(img_array.shape) == 3:
        grey = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        grey = img_array

    # Otsu binarisation
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Deskew using Hough line transform
    # np.where returns (rows, cols); minAreaRect expects (x, y) = (cols, rows)
    coords = np.column_stack(np.where(binary < 128))[:, ::-1]
    if len(coords) > 100:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) > 0.5:
            (h, w) = binary.shape
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            binary = cv2.warpAffine(binary, M, (w, h),
                                    flags=cv2.INTER_CUBIC,
                                    borderMode=cv2.BORDER_REPLICATE)

    # Denoise
    denoised = cv2.medianBlur(binary, 3)
    return denoised


def _ocr_page(pil_image: Image.Image, dpi: int = 300) -> tuple[str, float]:
    """
    Run Tesseract on a PIL image.
    Returns (text, mean_confidence).
    """
    # Upscale to target DPI if needed
    scale = dpi / 72
    new_w = int(pil_image.width * scale)
    new_h = int(pil_image.height * scale)
    pil_image = pil_image.resize((new_w, new_h), Image.LANCZOS)

    img_array = np.array(pil_image)
    processed = _preprocess_image(img_array)
    processed_pil = Image.fromarray(processed)

    # Single Tesseract pass — extract both text and confidence from image_to_data
    data = pytesseract.image_to_data(
        processed_pil,
        output_type=pytesseract.Output.DICT,
        config="--psm 6"
    )

    # Reconstruct text preserving line breaks so the segmentor's regex works.
    # Group word tokens by (block_num, par_num, line_num), then join with \n.
    lines: dict[tuple, list[str]] = {}
    for word, conf, block, par, line in zip(
        data["text"], data["conf"], data["block_num"], data["par_num"], data["line_num"]
    ):
        if str(conf).strip() in ("-1", "") or not word.strip():
            continue
        key = (block, par, line)
        lines.setdefault(key, []).append(word)

    text = "\n".join(" ".join(words) for words in lines.values())

    confidences = [int(c) for c in data["conf"] if str(c).strip() not in ("-1", "")]
    mean_conf = sum(confidences) / len(confidences) / 100 if confidences else 0.5

    return text.strip(), mean_conf


def _extract_native(pdf_path: str) -> list[dict]:
    """Extract text from a native (non-scanned) PDF using pdfplumber."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            # Crop out header/footer zones (top 8% and bottom 8%)
            h = page.height
            cropped = page.within_bbox((0, h * 0.08, page.width, h * 0.92))
            text = cropped.extract_text() or ""
            pages.append({
                "page": i + 1,
                "text": text.strip(),
                "ocr_confidence": 1.0,
                "method": "native"
            })
    return pages


def _extract_ocr(pdf_path: str, dpi: int = 300) -> list[dict]:
    """OCR every page of a scanned PDF."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            pil_image = page.to_image(resolution=dpi).original
            text, conf = _ocr_page(pil_image, dpi)
            pages.append({
                "page": i + 1,
                "text": text,
                "ocr_confidence": conf,
                "method": "ocr"
            })
    return pages


def load_pdf(pdf_path: str, min_chars_per_page: int = 50, dpi: int = 300) -> list[dict]:
    """
    F04 — Auto format detection.
    Tries native extraction first. If avg chars/page < min_chars_per_page,
    falls through to OCR.
    Returns list of page dicts: {page, text, ocr_confidence, method}
    """
    pdf_path = str(pdf_path)

    # Attempt native extraction
    native_pages = _extract_native(pdf_path)
    avg_chars = sum(len(p["text"]) for p in native_pages) / max(len(native_pages), 1)

    if avg_chars >= min_chars_per_page:
        return native_pages

    # Fall through to OCR
    print(f"  Native extraction got {avg_chars:.0f} chars/page -> switching to OCR")
    return _extract_ocr(pdf_path, dpi)


def pages_to_text(pages: list[dict], min_page_conf: float = 0.45) -> tuple[str, float]:
    """
    Merge page dicts into a single text block.
    Pages with OCR confidence below min_page_conf are skipped — they are
    typically dark/rotated scans that produce pure symbol gibberish and
    would pollute the segmentor with unreadable content.
    Returns (full_text, mean_confidence).
    """
    good_pages = [p for p in pages if p["ocr_confidence"] >= min_page_conf or p["method"] == "native"]
    if not good_pages:
        good_pages = pages  # fallback: keep everything if all pages are bad

    skipped = len(pages) - len(good_pages)
    if skipped:
        print(f"  Skipped {skipped} low-confidence page(s) (conf < {min_page_conf})")

    parts = [p["text"] for p in good_pages if p["text"]]
    full_text = "\n\n--- PAGE BREAK ---\n\n".join(parts)
    mean_conf = sum(p["ocr_confidence"] for p in good_pages) / max(len(good_pages), 1)
    return full_text, mean_conf