#!/usr/bin/env python3
"""
audit_docs.py — KB Health Gate + PDF pre-ingestion audit for TrustQueue.

KB audit (primary mode):
    python audit_docs.py --file farhad_kb.txt

PDF audit (legacy mode):
    python audit_docs.py --pdf path/to/document.pdf [--json] [--verbose]
"""

import argparse
import datetime
import difflib
import io
import json
import logging
import os
import re
import sys
import warnings

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Force UTF-8 on Windows consoles
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# ANSI colours (no external libs)
# ---------------------------------------------------------------------------
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# ---------------------------------------------------------------------------
# Level 2 constants
# ---------------------------------------------------------------------------
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.1-70b-versatile"

LLM_SYSTEM_PROMPT = (
    "You are a senior customer support operations auditor reviewing a knowledge base "
    "that will power an AI support bot. Analyze the KB and respond with ONLY valid JSON "
    "(no markdown, no prose) in this exact schema:\n"
    "{\n"
    '  "coverage_gaps": [list of important topics missing — pricing details, refund policy, technical specs, contact info],\n'
    '  "contradictions": [list of statements that contradict each other],\n'
    '  "vague_policies": [list of policies that are ambiguous or incomplete],\n'
    '  "missing_pricing_details": [list of pricing questions a customer would ask that cannot be answered],\n'
    '  "overall_score": integer 0-100,\n'
    '  "summary": "one sentence verdict"\n'
    "}\n\n"
    "Scoring rubric:\n"
    "- 90-100: production-ready\n"
    "- 70-89: usable but has gaps\n"
    "- 50-69: significant issues, risky to deploy\n"
    "- 0-49: unusable, will cause false handoffs"
)

# ---------------------------------------------------------------------------
# KB parsing
# ---------------------------------------------------------------------------

def parse_kb_chunks(text: str) -> list[str]:
    """Split on '## N.' section headers (TrustQueue KB format)."""
    parts = re.split(r"\n(?=## \d+\.)", text.strip())
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Level 1 — Structural checks
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def run_level1(text: str, chunks: list[str]) -> tuple[int, list[str]]:
    """Returns (score 0-100, list of result lines with PASS/FAIL prefix)."""
    results = []
    deductions = 0

    # 1. Total word count
    word_count = len(text.split())
    if word_count < 300:
        results.append(f"FAIL — Total word count: {word_count} words (minimum: 300)")
        deductions += 20
    else:
        results.append(f"PASS — Total word count: {word_count} words")

    # 2. Chunk count
    if len(chunks) < 5:
        results.append(f"FAIL — Chunk count: {len(chunks)} (minimum: 5)")
        deductions += 20
    else:
        results.append(f"PASS — Chunk count: {len(chunks)}")

    # 3. Average chunk length
    if chunks:
        avg_words = sum(len(c.split()) for c in chunks) / len(chunks)
    else:
        avg_words = 0
    if avg_words < 100:
        results.append(f"FAIL — Avg chunk length: {avg_words:.0f} words (minimum: 100)")
        deductions += 15
    elif avg_words > 2000:
        results.append(f"FAIL — Avg chunk length: {avg_words:.0f} words (maximum: 2000)")
        deductions += 15
    else:
        results.append(f"PASS — Avg chunk length: {avg_words:.0f} words")

    # 4. Duplicate chunk detection (>80% similarity)
    dup_pairs = []
    for i in range(len(chunks)):
        for j in range(i + 1, len(chunks)):
            sim = _similarity(chunks[i], chunks[j])
            if sim > 0.80:
                dup_pairs.append((i + 1, j + 1, sim))
    if dup_pairs:
        for a, b, sim in dup_pairs:
            results.append(f"FAIL — Chunks #{a} and #{b} are {sim:.0%} similar (near-duplicate)")
        deductions += 15
    else:
        results.append("PASS — No duplicate chunks detected")

    # 5. Source attribution
    missing_source = [i + 1 for i, c in enumerate(chunks) if "source:" not in c.lower()]
    if missing_source:
        results.append(f"FAIL — Chunks missing 'Source:' line: {missing_source}")
        deductions += 15
    else:
        results.append("PASS — All chunks have Source attribution")

    # 6. Section header format
    bad_headers = [i + 1 for i, c in enumerate(chunks) if not re.match(r"^## \d+\.", c)]
    if bad_headers:
        results.append(f"FAIL — Chunks not starting with '## N.' header: {bad_headers}")
        deductions += 15
    else:
        results.append("PASS — All chunks start with '## N.' header")

    score = max(0, 100 - deductions)
    return score, results


# ---------------------------------------------------------------------------
# Level 2 — LLM semantic audit
# ---------------------------------------------------------------------------

def _call_groq(api_key: str, kb_content: str) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user",   "content": f"Here is the knowledge base to audit:\n\n{kb_content}"},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
    }
    resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _strip_fences(raw: str) -> str:
    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def run_level2(api_key: str, kb_content: str) -> dict:
    """Returns parsed Groq JSON dict. Raises RuntimeError on any failure."""
    try:
        raw = _call_groq(api_key, kb_content)
    except Exception as e:
        raise RuntimeError(f"Groq API call failed: {e}")

    raw = _strip_fences(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Retry once
    try:
        raw2 = _call_groq(api_key, kb_content)
        raw2 = _strip_fences(raw2)
        return json.loads(raw2)
    except Exception as e:
        raise RuntimeError(f"Failed to parse Groq JSON response after retry: {e}\nLast raw output: {raw[:400]}")


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def _plist(label: str, items: list[str]) -> None:
    if items:
        print(f"  {YELLOW}{label}:{RESET}")
        for item in items:
            print(f"    • {item}")
    else:
        print(f"  {GREEN}{label}: none{RESET}")


def print_kb_report(
    filename: str,
    l1_score: int,
    l1_results: list[str],
    l2: dict,
    final_score: float,
) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}KB HEALTH GATE REPORT{RESET}")
    print(f"  File:      {filename}")
    print(f"  Timestamp: {now}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    print(f"\n{BOLD}LEVEL 1 — STRUCTURAL CHECKS  (score: {l1_score}/100){RESET}")
    for line in l1_results:
        colour = RED if line.startswith("FAIL") else GREEN
        print(f"  {colour}{line}{RESET}")

    l2_score = l2.get("overall_score", 0)
    print(f"\n{BOLD}LEVEL 2 — SEMANTIC AUDIT  (score: {l2_score}/100){RESET}")
    _plist("Coverage gaps",          l2.get("coverage_gaps", []))
    _plist("Contradictions",         l2.get("contradictions", []))
    _plist("Vague policies",         l2.get("vague_policies", []))
    _plist("Missing pricing details", l2.get("missing_pricing_details", []))
    print(f"  Summary: {l2.get('summary', '')}")

    print(f"\n{BOLD}FINAL SCORE BREAKDOWN{RESET}")
    print(f"  Level 1 (40%): {l1_score:3d} × 0.4 = {l1_score * 0.4:5.1f}")
    print(f"  Level 2 (60%): {l2_score:3d} × 0.6 = {l2_score * 0.6:5.1f}")
    print(f"  {'─' * 30}")
    print(f"  Final score:          {final_score:5.1f} / 100")


# ---------------------------------------------------------------------------
# KB audit entry point
# ---------------------------------------------------------------------------

def audit_kb(filepath: str) -> None:
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"{RED}Error: File not found: {filepath}{RESET}", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print(
            f"{RED}Error: GROQ_API_KEY not set. "
            f"Add it to the .env file in the script directory.{RESET}",
            file=sys.stderr,
        )
        sys.exit(2)

    chunks = parse_kb_chunks(content)

    l1_score, l1_results = run_level1(content, chunks)

    print(f"Running Level 2 semantic audit via Groq ({GROQ_MODEL})…")
    try:
        l2 = run_level2(api_key, content)
    except RuntimeError as e:
        print(f"{RED}Error: {e}{RESET}", file=sys.stderr)
        sys.exit(2)

    l2_score    = l2.get("overall_score", 0)
    final_score = (l1_score * 0.4) + (l2_score * 0.6)

    print_kb_report(filepath, l1_score, l1_results, l2, final_score)

    print(f"\n{BOLD}VERDICT{RESET}")

    if final_score >= 85:
        print(f"{GREEN}{BOLD}✅ KB APPROVED — Ready for ingestion{RESET}")
        sys.exit(0)

    elif final_score >= 70:
        print(f"{YELLOW}{BOLD}⚠️  KB WARNING — Usable but has issues (score: {final_score:.1f}/100){RESET}")
        try:
            answer = input("Proceed anyway? (y/N): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            answer = ""
        if answer in ("y", "yes"):
            print(f"{YELLOW}Proceeding with warnings.{RESET}")
            sys.exit(0)
        else:
            print(f"{RED}Aborted.{RESET}")
            sys.exit(1)

    else:
        print(
            f"{RED}{BOLD}❌ KB REJECTED — Score {final_score:.1f}/100 is below minimum threshold (70). "
            f"Fix issues and re-run.{RESET}"
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# PDF audit (preserved — original audit_docs.py logic)
# ---------------------------------------------------------------------------

def audit_pdf(pdf_path: str, verbose: bool = False, output_json: bool = False) -> None:
    import pdfplumber

    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message=".*FontBBox.*")

    try:
        report = _run_pdf_audit(pdf_path, verbose=verbose)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if output_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(_format_pdf_markdown(report))

    sys.exit(2 if report["overall_score"] < 0.50 else 0)


def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start: start + chunk_size])
        if start + chunk_size >= len(text):
            break
        start += chunk_size - overlap
    return chunks


def _score_extractability(pages_text: list[str]) -> tuple[float, list[str]]:
    if not pages_text:
        return 0.0, ["No pages found in PDF"]
    flags, good = [], 0
    for i, text in enumerate(pages_text, 1):
        stripped = text.strip()
        if len(stripped) > 50:
            good += 1
        else:
            flags.append(f"Page {i}: little or no extractable text ({len(stripped)} chars)")
    return good / len(pages_text), flags


def _score_tables(pdf) -> tuple[float, list[str]]:
    flags, total, good = [], 0, 0
    for i, page in enumerate(pdf.pages, 1):
        for t_idx, table in enumerate(page.find_tables(), 1):
            total += 1
            extracted = table.extract()
            if (
                extracted
                and len(extracted) >= 2
                and all(any(cell for cell in row) for row in extracted)
            ):
                good += 1
            else:
                row_count = len(extracted) if extracted else 0
                flags.append(f"Page {i}, table {t_idx}: detected but poorly structured ({row_count} rows)")
    if total == 0:
        return 1.0, []
    return good / total, flags


def _score_headers(pdf) -> tuple[float, list[str]]:
    flags, font_sizes = [], set()
    for page in pdf.pages:
        for ch in page.chars:
            size = ch.get("size")
            if size is not None:
                font_sizes.add(round(float(size), 1))
    if not font_sizes:
        return 0.0, ["No character-level font data found"]
    distinct = len(font_sizes)
    if distinct >= 3:
        return 1.0, []
    elif distinct == 2:
        return 0.65, ["Only 2 distinct font sizes — limited heading hierarchy"]
    else:
        return 0.3, ["Single font size throughout — no detectable headings"]


def _score_chunk_density(full_text: str) -> tuple[float, list[str]]:
    flags = []
    chunks = _chunk_text(full_text, 1000, 200)
    if not chunks:
        return 0.0, ["No text to chunk"]
    good = 0
    for i, chunk in enumerate(chunks):
        meaningful = len(chunk.strip())
        if meaningful >= 200:
            good += 1
        else:
            flags.append(f"Chunk #{i} ({len(chunk)} chars): only {meaningful} meaningful characters")
    return good / len(chunks), flags


def _score_encoding(full_text: str) -> tuple[float, list[str]]:
    if not full_text:
        return 1.0, []
    encoded   = full_text.encode("utf-8", errors="replace")
    decoded   = encoded.decode("utf-8")
    replacements = decoded.count("\ufffd")
    if replacements == 0:
        return 1.0, []
    ratio = max(1.0 - (replacements / len(full_text)), 0.0)
    return ratio, [f"{replacements} characters failed UTF-8 round-trip"]


_PDF_WEIGHTS = {
    "Text Extractability": 0.30,
    "Table Structure":     0.25,
    "Header Hierarchy":    0.20,
    "Chunk Density":       0.15,
    "Encoding":            0.10,
}


def _run_pdf_audit(pdf_path: str, verbose: bool = False) -> dict:
    import pdfplumber
    pdf        = pdfplumber.open(pdf_path)
    pages_text = [page.extract_text() or "" for page in pdf.pages]
    full_text  = "\n".join(pages_text)
    dimensions, all_flags = {}, []

    for scorer, key in [
        (_score_extractability, "Text Extractability"),
        (_score_tables,         "Table Structure"),
        (_score_headers,        "Header Hierarchy"),
        (_score_chunk_density,  "Chunk Density"),
        (_score_encoding,       "Encoding"),
    ]:
        if key in ("Table Structure", "Header Hierarchy"):
            s, f = scorer(pdf)
        elif key == "Text Extractability":
            s, f = scorer(pages_text)
        elif key == "Chunk Density":
            s, f = scorer(full_text)
        else:
            s, f = scorer(full_text)
        dimensions[key] = s
        all_flags.extend(f)

    pdf.close()
    overall = round(sum(dimensions[k] * _PDF_WEIGHTS[k] for k in _PDF_WEIGHTS), 2)
    chunks  = _chunk_text(full_text, 1000, 200)

    verdict = (
        "✅ READY — safe to ingest" if overall >= 0.75
        else "⚠️ FAIR — ingest with caution, review flagged sections" if overall >= 0.50
        else "❌ NOT READY — fix issues before ingestion"
    )
    return {
        "file": pdf_path,
        "pages": len(pages_text),
        "total_chars": len(full_text),
        "simulated_chunks": len(chunks),
        "overall_score": overall,
        "verdict": verdict,
        "dimensions": {k: round(v, 2) for k, v in dimensions.items()},
        "flags": all_flags,
    }


def _format_pdf_markdown(report: dict) -> str:
    lines = [
        f"# Doc Health Report: {report['file']}",
        f"**Pages:** {report['pages']}  |  "
        f"**Characters:** {report['total_chars']:,}  |  "
        f"**Simulated chunks:** {report['simulated_chunks']}",
        "",
        f"## Overall Score: {report['overall_score']:.2f} / 1.00",
        f"## RAG Readiness: {report['verdict']}",
        "",
        "| Dimension            | Score | Weight |",
        "|----------------------|-------|--------|",
    ]
    for dim, score in report["dimensions"].items():
        lines.append(f"| {dim:<20} | {score:.2f}  | {_PDF_WEIGHTS[dim]:.0%}   |")
    lines.append("")
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

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TrustQueue KB Health Gate and PDF audit tool."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--file", metavar="KB_FILE",
                      help="Path to TrustQueue-format KB text file to audit (KB gate mode)")
    mode.add_argument("--pdf", metavar="PDF_FILE",
                      help="Path to PDF file to audit (legacy PDF mode)")

    parser.add_argument("--json", action="store_true", dest="output_json",
                        help="[PDF mode] Output machine-readable JSON")
    parser.add_argument("--verbose", action="store_true",
                        help="[PDF mode] Include extra detail in output")
    args = parser.parse_args()

    if args.file:
        audit_kb(args.file)
    else:
        audit_pdf(args.pdf, verbose=args.verbose, output_json=args.output_json)


if __name__ == "__main__":
    main()
