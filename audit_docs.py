#!/usr/bin/env python3
"""
audit_docs.py — Pre-ingestion PDF health check for TrustQueue.

Analyses a PDF for text extractability, table structure, header hierarchy,
chunk density, and encoding cleanliness, then produces a Doc Health Report
predicting how well the document will perform in the RAG pipeline.

Usage:
    python audit_docs.py path/to/document.pdf [--json] [--verbose]
"""

import argparse
import json
import math
import sys
import io

import logging
import warnings

import pdfplumber

# Suppress noisy pdfplumber/pdfminer font warnings
logging.getLogger("pdfminer").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*FontBBox.*")

# Force UTF-8 on Windows consoles that default to legacy codepages
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Chunking logic — mirrors app/api/ingest.py chunk_text() exactly
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    chunks = []
    start = 0
    text_length = len(text)
    while start < text_length:
        chunks.append(text[start : start + chunk_size])
        if start + chunk_size >= text_length:
            break
        start += chunk_size - overlap
    return chunks


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def score_extractability(pages_text: list[str]) -> tuple[float, list[str]]:
    """Ratio of pages with >50 chars of extractable text."""
    if not pages_text:
        return 0.0, ["No pages found in PDF"]

    flags = []
    good = 0
    for i, text in enumerate(pages_text, 1):
        stripped = text.strip()
        if len(stripped) > 50:
            good += 1
        else:
            flags.append(f"Page {i}: little or no extractable text ({len(stripped)} chars)")

    score = good / len(pages_text)
    return score, flags


def score_tables(pdf: pdfplumber.PDF) -> tuple[float, list[str]]:
    """Ratio of well-formed tables vs total detected tables."""
    flags = []
    total_tables = 0
    good_tables = 0

    for i, page in enumerate(pdf.pages, 1):
        tables = page.find_tables()
        for t_idx, table in enumerate(tables, 1):
            total_tables += 1
            extracted = table.extract()
            # A table is "good" if it has >=2 rows and no row is entirely None
            if (
                extracted
                and len(extracted) >= 2
                and all(any(cell for cell in row) for row in extracted)
            ):
                good_tables += 1
            else:
                row_count = len(extracted) if extracted else 0
                flags.append(
                    f"Page {i}, table {t_idx}: detected but poorly structured ({row_count} rows)"
                )

    if total_tables == 0:
        return 1.0, []  # No tables is fine — not every doc has them

    score = good_tables / total_tables
    return score, flags


def score_headers(pages_text: list[str], pdf: pdfplumber.PDF) -> tuple[float, list[str]]:
    """Detect font-size variation that suggests section headings."""
    flags = []
    font_sizes = set()

    for page in pdf.pages:
        chars = page.chars
        for ch in chars:
            size = ch.get("size")
            if size is not None:
                font_sizes.add(round(float(size), 1))

    if len(font_sizes) == 0:
        return 0.0, ["No character-level font data found"]

    # A well-structured doc typically has >=3 distinct font sizes
    # (body, heading, sub-heading). 2 is acceptable. 1 is flat.
    distinct = len(font_sizes)
    if distinct >= 3:
        score = 1.0
    elif distinct == 2:
        score = 0.65
        flags.append("Only 2 distinct font sizes — limited heading hierarchy")
    else:
        score = 0.3
        flags.append("Single font size throughout — no detectable headings")

    return score, flags


def score_chunk_density(full_text: str) -> tuple[float, list[str]]:
    """Simulate the 1000/200 chunker and flag sparse chunks."""
    flags = []
    chunks = chunk_text(full_text, 1000, 200)

    if not chunks:
        return 0.0, ["No text to chunk"]

    good = 0
    for i, chunk in enumerate(chunks):
        meaningful = len(chunk.strip())
        if meaningful >= 200:
            good += 1
        else:
            flags.append(f"Chunk #{i} ({len(chunk)} chars): only {meaningful} meaningful characters")

    score = good / len(chunks)
    return score, flags


def score_encoding(full_text: str) -> tuple[float, list[str]]:
    """Ratio of characters that survive a UTF-8 round-trip cleanly."""
    flags = []
    if not full_text:
        return 1.0, []

    encoded = full_text.encode("utf-8", errors="replace")
    decoded = encoded.decode("utf-8")
    replacements = decoded.count("\ufffd")

    if replacements == 0:
        return 1.0, []

    ratio = 1.0 - (replacements / len(full_text))
    score = max(ratio, 0.0)
    flags.append(f"{replacements} characters failed UTF-8 round-trip")
    return score, flags


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

WEIGHTS = {
    "Text Extractability": 0.30,
    "Table Structure": 0.25,
    "Header Hierarchy": 0.20,
    "Chunk Density": 0.15,
    "Encoding": 0.10,
}


def rag_verdict(overall: float) -> str:
    if overall >= 0.75:
        return "\u2705 READY \u2014 safe to ingest"
    elif overall >= 0.50:
        return "\u26a0\ufe0f FAIR \u2014 ingest with caution, review flagged sections"
    else:
        return "\u274c NOT READY \u2014 fix issues before ingestion"


def run_audit(pdf_path: str, verbose: bool = False) -> dict:
    pdf = pdfplumber.open(pdf_path)
    pages_text = [page.extract_text() or "" for page in pdf.pages]
    full_text = "\n".join(pages_text)

    dimensions = {}
    all_flags = []

    # Run each scorer
    s1, f1 = score_extractability(pages_text)
    dimensions["Text Extractability"] = s1
    all_flags.extend(f1)

    s2, f2 = score_tables(pdf)
    dimensions["Table Structure"] = s2
    all_flags.extend(f2)

    s3, f3 = score_headers(pages_text, pdf)
    dimensions["Header Hierarchy"] = s3
    all_flags.extend(f3)

    s4, f4 = score_chunk_density(full_text)
    dimensions["Chunk Density"] = s4
    all_flags.extend(f4)

    s5, f5 = score_encoding(full_text)
    dimensions["Encoding"] = s5
    all_flags.extend(f5)

    pdf.close()

    overall = sum(dimensions[k] * WEIGHTS[k] for k in WEIGHTS)
    overall = round(overall, 2)

    chunks = chunk_text(full_text, 1000, 200)

    return {
        "file": pdf_path,
        "pages": len(pages_text),
        "total_chars": len(full_text),
        "simulated_chunks": len(chunks),
        "overall_score": overall,
        "verdict": rag_verdict(overall),
        "dimensions": {k: round(v, 2) for k, v in dimensions.items()},
        "flags": all_flags,
    }


def format_markdown(report: dict) -> str:
    lines = []
    lines.append(f"# Doc Health Report: {report['file']}")
    lines.append(f"**Pages:** {report['pages']}  |  "
                 f"**Characters:** {report['total_chars']:,}  |  "
                 f"**Simulated chunks:** {report['simulated_chunks']}")
    lines.append("")
    lines.append(f"## Overall Score: {report['overall_score']:.2f} / 1.00")
    lines.append(f"## RAG Readiness: {report['verdict']}")
    lines.append("")

    # Dimensions table
    lines.append("| Dimension            | Score | Weight |")
    lines.append("|----------------------|-------|--------|")
    for dim, score in report["dimensions"].items():
        weight = WEIGHTS[dim]
        lines.append(f"| {dim:<20} | {score:.2f}  | {weight:.0%}   |")
    lines.append("")

    # Flags
    if report["flags"]:
        lines.append(f"## Flagged Issues ({len(report['flags'])})")
        for flag in report["flags"]:
            lines.append(f"- {flag}")
    else:
        lines.append("## No issues flagged")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Pre-ingestion PDF health check for TrustQueue RAG pipeline."
    )
    parser.add_argument("pdf_path", help="Path to the PDF file to audit")
    parser.add_argument("--json", action="store_true", dest="output_json",
                        help="Output machine-readable JSON instead of markdown")
    parser.add_argument("--verbose", action="store_true",
                        help="Include extra detail in output")
    args = parser.parse_args()

    try:
        report = run_audit(args.pdf_path, verbose=args.verbose)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_markdown(report))

    # Exit code reflects verdict
    if report["overall_score"] < 0.50:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
