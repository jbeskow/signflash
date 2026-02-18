#!/usr/bin/env python3
"""Generate a SignFlash wordlist JS file.

Modes:
  From a word file:
    python3 gen_wordlist.py --wordfile words.txt --id mylist --name "My List" -o wordlists/mylist.js

  From a category (most frequent words):
    python3 gen_wordlist.py --category Familj --id familj --name "Familj" -o wordlists/familj.js

  Both (filter word file to category):
    python3 gen_wordlist.py --wordfile words.txt --category Familj --id familj --name "Familj" -o wordlists/familj.js

Uses sign_data.csv for word/video/category lookup and stats_PAROLE.txt
frequency dictionary to select the --maxlength most common words.
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
import urllib.error


def rebuild_all_js(wordlists_dir):
    """Concatenate all .js files in wordlists/ (except all.js) into all.js."""
    files = sorted(f for f in os.listdir(wordlists_dir)
                   if f.endswith(".js") and f != "all.js")
    all_path = os.path.join(wordlists_dir, "all.js")
    with open(all_path, "w", encoding="utf-8") as out:
        out.write("// Auto-generated — do not edit. Run: python3 gen_wordlist.py --rebuild\n")
        for f in files:
            out.write(f"\n// --- {f} ---\n")
            with open(os.path.join(wordlists_dir, f), encoding="utf-8") as inp:
                out.write(inp.read())
    print(f"Rebuilt wordlists/all.js ({len(files)} wordlists: {', '.join(files)})")


def load_sign_data(csv_path):
    """Load sign_data.csv → list of row dicts."""
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_frequency(freq_path):
    """Load stats_PAROLE.txt → dict of word → rank (lower = more common)."""
    freq = {}
    rank = 0
    with open(freq_path, encoding="utf-8") as f:
        for line in f:
            parts = line.split("\t")
            if len(parts) >= 5:
                word = parts[0].strip().lower()
                if word and word not in freq:
                    freq[word] = rank
                    rank += 1
    return freq


def extract_video_filename(movie_path):
    """Extract just the filename from e.g. 'movies/00/mossa-00003-tecken.mp4'."""
    return movie_path.rsplit("/", 1)[-1] if "/" in movie_path else movie_path


def check_video_url(filename):
    """Check if the video exists on su.se via HTTP HEAD request."""
    match = re.search(r"-(\d{5})-tecken\.mp4$", filename)
    if not match:
        return False
    prefix = match.group(1)[:2]
    url = f"https://teckensprakslexikon.su.se/movies/{prefix}/{filename}"
    req = urllib.request.Request(url, method="HEAD")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 200
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Generate a SignFlash wordlist JS file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 gen_wordlist.py --category Familj --id familj --name "Familj" -o wordlists/familj.js
  python3 gen_wordlist.py --category "Djur / Däggdjur" --maxlength 50 --id djur --name "Djur" -o wordlists/djur.js
  python3 gen_wordlist.py --wordfile words.txt --id custom --name "Custom" -o wordlists/custom.js
  python3 gen_wordlist.py --list-categories
""")
    parser.add_argument("--wordfile", default=None, help="Text file with one word per line (optional if --category used)")
    parser.add_argument("--category", default=None, help="Filter to words in this category (from sign_data.csv)")
    parser.add_argument("--maxlength", type=int, default=100, help="Maximum number of words (default: 100)")
    parser.add_argument("--id", default=None, help="Wordlist ID (e.g. 'mylist')")
    parser.add_argument("--name", default=None, help="Display name (e.g. 'My List')")
    parser.add_argument("-o", "--output", default=None, help="Output JS file path")
    parser.add_argument("--csv", default=None, help="Path to sign_data.csv (default: same dir as script)")
    parser.add_argument("--freq", default=None, help="Path to stats_PAROLE.txt (default: same dir as script)")
    parser.add_argument("--no-verify", action="store_true", help="Skip video URL verification")
    parser.add_argument("--list-categories", action="store_true", help="List all categories and exit")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild wordlists/all.js and exit")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = args.csv or os.path.join(script_dir, "sign_data.csv")
    freq_path = args.freq or os.path.join(script_dir, "stats_PAROLE.txt")

    wordlists_dir = os.path.join(script_dir, "wordlists")

    if args.rebuild:
        rebuild_all_js(wordlists_dir)
        return

    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading sign data: {csv_path}")
    sign_rows = load_sign_data(csv_path)
    print(f"Loaded {len(sign_rows)} entries from sign_data.csv")

    # --- List categories mode ---
    if args.list_categories:
        cats = {}
        for row in sign_rows:
            c = row.get("category", "").strip()
            if c:
                cats[c] = cats.get(c, 0) + 1
        for c in sorted(cats.keys()):
            print(f"  {c} ({cats[c]} words)")
        return

    # Validate required args for generation
    if not args.id or not args.name or not args.output:
        parser.error("--id, --name, and -o/--output are required for generation")

    if not args.wordfile and not args.category:
        parser.error("At least one of --wordfile or --category is required")

    # --- Build candidate words ---

    # Build word → sign data lookup (word → first matching row)
    word_lookup = {}
    for row in sign_rows:
        word = row["word"].strip().lower()
        cat = row.get("category", "").strip()
        movie = row.get("movie", "").strip()
        if not movie:
            continue
        if args.category and not cat.lower().startswith(args.category.lower()):
            continue
        if word not in word_lookup:
            word_lookup[word] = row

    if args.category:
        matched_cats = set()
        for row in sign_rows:
            cat = row.get("category", "").strip()
            if cat and cat.lower().startswith(args.category.lower()):
                matched_cats.add(cat)
        if matched_cats:
            print(f"Category '{args.category}' matched: {', '.join(sorted(matched_cats))} ({len(word_lookup)} words)")
        else:
            print(f"Category '{args.category}': no matches found")

    # If wordfile provided, use it as the candidate list
    if args.wordfile:
        with open(args.wordfile, encoding="utf-8") as f:
            input_words = [line.strip().lower() for line in f if line.strip()]
        candidates = []
        warnings = []
        for w in input_words:
            if w in word_lookup:
                candidates.append(w)
            else:
                warnings.append(f"NOT FOUND: '{w}'" + (f" (not in category '{args.category}')" if args.category else ""))
        if warnings:
            for w in warnings:
                print(f"  Warning: {w}")
    else:
        candidates = list(word_lookup.keys())

    # --- Rank by frequency ---

    if not os.path.exists(freq_path):
        print(f"Warning: Frequency file not found: {freq_path}, using alphabetical order", file=sys.stderr)
        freq = {}
    else:
        print(f"Loading frequency data: {freq_path}")
        freq = load_frequency(freq_path)
        print(f"Loaded {len(freq)} unique word forms")

    max_rank = len(freq)
    candidates.sort(key=lambda w: freq.get(w, max_rank))

    # Trim to maxlength
    if len(candidates) > args.maxlength:
        dropped = candidates[args.maxlength:]
        candidates = candidates[:args.maxlength]
        print(f"Trimmed to {args.maxlength} most frequent words (dropped {len(dropped)})")
    else:
        print(f"Selected {len(candidates)} words")

    # --- Build entries with video verification ---

    entries = []
    warnings = []

    for word in candidates:
        row = word_lookup[word]
        filename = extract_video_filename(row["movie"])

        if not args.no_verify:
            print(f"  Checking: {word} -> {filename} ...", end=" ", flush=True)
            if check_video_url(filename):
                print("OK")
                entries.append({"word": word, "video": filename})
            else:
                print("MISSING")
                warnings.append(f"VIDEO MISSING: '{word}' -> {filename}")
        else:
            entries.append({"word": word, "video": filename})

    # --- Output JS file ---

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write('(window.WORDLISTS = window.WORDLISTS || []).push({\n')
        f.write(f'  id: {json.dumps(args.id, ensure_ascii=False)},\n')
        f.write(f'  name: {json.dumps(args.name, ensure_ascii=False)},\n')
        f.write('  words: [\n')
        for i, entry in enumerate(entries):
            comma = "," if i < len(entries) - 1 else ""
            f.write(f'    {{ word: {json.dumps(entry["word"], ensure_ascii=False)}, video: {json.dumps(entry["video"], ensure_ascii=False)} }}{comma}\n')
        f.write('  ]\n')
        f.write('});\n')

    print(f"\nWrote {len(entries)} words to {args.output}")

    # Auto-rebuild all.js if output is inside wordlists/
    output_dir = os.path.dirname(os.path.abspath(args.output))
    if os.path.samefile(output_dir, wordlists_dir):
        rebuild_all_js(wordlists_dir)

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(f"  {w}")

    if len(entries) == 0:
        print("\nNo valid entries generated!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
