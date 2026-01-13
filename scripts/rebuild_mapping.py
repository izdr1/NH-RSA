#!/usr/bin/env python3
"""
Build chapter_to_title.json from the NH RSA Table of Contents.

Outputs: data/chapter_to_title.json
Input modes:
  --source live       Fetch https://gc.nh.gov/rsa/html/nhtoc.htm
  --source fixture    Read fixtures/nhtoc.html (recommended for development)

This mapping lets you turn 'RSA 225-A:24' into:
  https://gc.nh.gov/rsa/html/xix/225-a/225-a-24.htm
"""

import argparse
import json
import os
import re
import sys
from urllib.request import Request, urlopen

TOC_URL = "https://gc.nh.gov/rsa/html/nhtoc.htm"
BASE_OUT = os.path.join("data", "chapter_to_title.json")
FIXTURE = os.path.join("fixtures", "nhtoc.html")


def suffix_to_int(sfx: str | None) -> int:
    """A=1, B=2, ... Z=26, AA=27, etc. None/empty -> 0"""
    if not sfx:
        return 0
    sfx = sfx.upper()
    n = 0
    for ch in sfx:
        if not ("A" <= ch <= "Z"):
            break
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def parse_chapter_token(tok: str) -> tuple[int, int]:
    """
    '225-A' -> (225, 1)
    '227-F' -> (227, 6)
    '216'   -> (216, 0)
    """
    tok = tok.strip().upper()
    m = re.fullmatch(r"(\d+)(?:-([A-Z]+))?", tok)
    if not m:
        raise ValueError(f"Bad chapter token: {tok!r}")
    return int(m.group(1)), suffix_to_int(m.group(2))


def chapter_token_le(a: str, b: str) -> bool:
    return parse_chapter_token(a) <= parse_chapter_token(b)


def token_between(x: str, start: str, end: str) -> bool:
    px = parse_chapter_token(x)
    return parse_chapter_token(start) <= px <= parse_chapter_token(end)


def read_html(source: str) -> str:
    if source == "fixture":
        if not os.path.exists(FIXTURE):
            raise FileNotFoundError(
                f"Fixture not found at {FIXTURE}. Upload the TOC as fixtures/nhtoc.html"
            )
        with open(FIXTURE, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    if source == "live":
        req = Request(
            TOC_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")

    raise ValueError("--source must be 'live' or 'fixture'")


def extract_title_ranges(toc_html: str) -> list[dict]:
    """
    Returns list like:
      {"title_key":"XIX", "folder":"xix", "start":"216", "end":"227-F"}
      {"title_key":"XIX-A", "folder":"xix-a", "start":"227-G", "end":"227-M"}
    We parse from the TOC's text patterns: "TITLE XIX" and "(Includes Chapters 216 - 227-F)"
    """
    # Normalize whitespace a bit
    text = re.sub(r"[ \t]+", " ", toc_html)
    text = re.sub(r"\r\n?", "\n", text)

    # Find every "TITLE ..." occurrence and grab some following text window
    # We'll search in windows because HTML structure can vary.
    title_iter = list(re.finditer(r"\bTITLE\s+([IVXLCDM]+(?:-A)?)\b", text, flags=re.IGNORECASE))

    ranges: list[dict] = []
    for i, m in enumerate(title_iter):
        title_key = m.group(1).upper()
        folder = title_key.lower()

        # Take a window after the title
        start_idx = m.end()
        end_idx = title_iter[i + 1].start() if i + 1 < len(title_iter) else min(len(text), start_idx + 2500)
        window = text[start_idx:end_idx]

        # Range patterns:
        # "(Includes Chapters 216 - 227-F)" OR "(Includes Chapter 288)"
        m_range = re.search(
            r"Includes\s+Chapters?\s+(\d+(?:-[A-Z]+)?)\s*-\s*(\d+(?:-[A-Z]+)?)",
            window,
            flags=re.IGNORECASE,
        )
        if m_range:
            ranges.append(
                {
                    "title_key": title_key,
                    "folder": folder,
                    "start": m_range.group(1).upper(),
                    "end": m_range.group(2).upper(),
                }
            )
            continue

        m_single = re.search(
            r"Includes\s+Chapter\s+(\d+(?:-[A-Z]+)?)",
            window,
            flags=re.IGNORECASE,
        )
        if m_single:
            ch = m_single.group(1).upper()
            ranges.append({"title_key": title_key, "folder": folder, "start": ch, "end": ch})
            continue

        # If we can't find a range, skip (repealed titles etc.)
    return ranges


def build_chapter_to_title(ranges: list[dict]) -> dict[str, str]:
    """
    Expand title ranges into a mapping for *existing chapters* we can infer.
    BUT we can't know every missing chapter number (gaps), so instead we store ranges
    and resolve chapters by scanning ranges at runtime.

    For the static site, we want O(1) lookup, so we *also* extract actual chapter folders
    from links if present. The TOC often includes per-chapter links; we'll attempt that first.
    Fallback is range-based (works for most).
    """
    # Best: extract chapter->folder from explicit chapter links in HTML when available
    # Link pattern typically contains /rsa/html/{folder}/{chapter}/...
    # We'll parse any occurrences.
    mapping: dict[str, str] = {}
    link_re = re.compile(r"/rsa/html/([a-z0-9\-]+)/(\d+(?:-[a-z])?)/", flags=re.IGNORECASE)
    for folder, chapter in link_re.findall(toc_html_global):
        mapping[chapter.lower()] = folder.lower()

    # If mapping is empty (structure changed), we'll at least use ranges at runtime.
    # But for JSON, we can store ranges too.
    return mapping


def resolve_folder_by_range(chapter: str, ranges: list[dict]) -> str | None:
    ch = chapter.strip().upper()
    for r in ranges:
        if token_between(ch, r["start"], r["end"]):
            return r["folder"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["live", "fixture"], default="fixture")
    ap.add_argument("--out", default=BASE_OUT)
    args = ap.parse_args()

    global toc_html_global
    toc_html_global = read_html(args.source)

    ranges = extract_title_ranges(toc_html_global)

    # Build mapping from explicit links if possible
    mapping: dict[str, str] = {}
    link_re = re.compile(r"/rsa/html/([a-z0-9\-]+)/(\d+(?:-[a-z])?)/", flags=re.IGNORECASE)
    for folder, chapter in link_re.findall(toc_html_global):
        mapping[chapter.lower()] = folder.lower()

    payload = {
        "generated_from": args.source,
        "toc_url": TOC_URL,
        "chapter_to_title": dict(sorted(mapping.items())),
        "title_ranges": ranges,  # keep ranges as fallback
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    # Simple sanity check print
    test_ch = "225-A"
    folder = mapping.get(test_ch.lower()) or resolve_folder_by_range(test_ch, ranges)
    print(f"Wrote {args.out}. Example {test_ch} -> folder {folder!r}")

    if not ranges:
        print("WARNING: No title ranges found. The TOC format may have changed.", file=sys.stderr)


if __name__ == "__main__":
    main()
