#!/usr/bin/env python3
"""Generate a SignFlash wordlist JS file.

Workflow:
  1. Generate with --phrases (auto-bracket):
     python3 gen_wordlist.py --category familj --id familj --name "Familj" --phrases

  2. Review lists/{id}.js, check bracket correctness.

  3. For tricky inflections, re-run with --ai-bracket (Haiku API):
     python3 gen_wordlist.py --category familj --id familj --name "Familj" --phrases --ai-bracket

  4. Edit manually for edge cases.

Modes:
  From a word file:
    python3 gen_wordlist.py --wordfile words.txt --id mylist --name "My List"

  From a category slug (most frequent words):
    python3 gen_wordlist.py --category familj --id familj --name "Familj"

  Multiple category slugs (comma-separated):
    python3 gen_wordlist.py --category djur,natur --id djur --name "Djur & Natur"

  Both (filter word file to category):
    python3 gen_wordlist.py --wordfile words.txt --category familj --id familj --name "Familj"

Uses sign_data.csv for word/video/category lookup and stats_PAROLE.txt
frequency dictionary to select the --maxlength most common words.
"""

import argparse
import ast
import csv
import json
import math
import os
import re
import sys
import urllib.request
import urllib.error


def rebuild_all_js(lists_dir):
    """Concatenate all .js files in lists/ (except all.js) into all.js."""
    files = sorted(f for f in os.listdir(lists_dir)
                   if f.endswith(".js") and f != "all.js")
    all_path = os.path.join(lists_dir, "all.js")
    with open(all_path, "w", encoding="utf-8") as out:
        out.write("// Auto-generated — do not edit. Run: python3 gen_wordlist.py --rebuild\n")
        for f in files:
            out.write(f"\n// --- {f} ---\n")
            with open(os.path.join(lists_dir, f), encoding="utf-8") as inp:
                out.write(inp.read())
    print(f"Rebuilt lists/all.js ({len(files)} wordlists: {', '.join(files)})")


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


BOK_SLUG = "bokstavering"


def is_bokstavering_row(row):
    """Return True if row is pure fingerspelling (no combined sign)."""
    desc = row.get("description", "")
    return desc.startswith("Bokstaveras:") and "//" not in desc


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


def parse_phrases_column(phrases_str):
    """Parse the 'phrases' column from sign_data.csv.

    The column is a Python list-of-dicts literal like:
    [{'phrase': 'Hunden skäller.', 'movie': 'movies/00/hund-00222-fras-1.mp4'}]
    """
    if not phrases_str or not phrases_str.strip():
        return []
    try:
        result = ast.literal_eval(phrases_str.strip())
        if isinstance(result, list):
            return result
        return []
    except (ValueError, SyntaxError):
        return []


def auto_bracket(word, phrase_text):
    """Regex-bracket stem-sharing forms of word in phrase_text."""
    return re.sub(
        rf"(?<!\[)(?<!\w)({re.escape(word)}\w*)(?!\])",
        r"[\1]",
        phrase_text,
        flags=re.IGNORECASE,
    )


def ai_bracket(word, phrase_text, client):
    """Use Claude Haiku to bracket inflected/derived forms of word in phrase_text."""
    prompt = (
        f'Swedish base word: "{word}"\n'
        f'Phrase: "{phrase_text}"\n'
        f'Wrap ALL occurrences of this word and its inflected or derived forms '
        f'(including compounds) in [square brackets]. Return ONLY the phrase.'
    )
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip().strip('"')


def write_wordlist_js(output_path, wl_id, wl_name, entries, phrase_entries):
    """Write a single wordlist JS file."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write('(window.WORDLISTS = window.WORDLISTS || []).push({\n')
        f.write(f'  id: {json.dumps(wl_id, ensure_ascii=False)},\n')
        f.write(f'  name: {json.dumps(wl_name, ensure_ascii=False)},\n')
        f.write('  words: [\n')
        for i, entry in enumerate(entries):
            comma = "," if i < len(entries) - 1 else ""
            f.write(f'    {{ word: {json.dumps(entry["word"], ensure_ascii=False)}, video: {json.dumps(entry["video"], ensure_ascii=False)} }}{comma}\n')
        f.write('  ]')
        if phrase_entries:
            f.write(',\n  phrases: [\n')
            for i, pe in enumerate(phrase_entries):
                comma = "," if i < len(phrase_entries) - 1 else ""
                f.write(f'    {{ word: {json.dumps(pe["word"], ensure_ascii=False)}, phrase: {json.dumps(pe["phrase"], ensure_ascii=False)}, video: {json.dumps(pe["video"], ensure_ascii=False)} }}{comma}\n')
            f.write('  ]\n')
        else:
            f.write('\n')
        f.write('});\n')


def main():
    parser = argparse.ArgumentParser(
        description="Generate a SignFlash wordlist JS file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 gen_wordlist.py --category familj --id familj --name "Familj"
  python3 gen_wordlist.py --category djur --maxlength 50 --id djur --name "Djur"
  python3 gen_wordlist.py --category djur,natur --id djur --name "Djur & Natur"
  python3 gen_wordlist.py --wordfile words.txt --id custom --name "Custom"
  python3 gen_wordlist.py --list-categories
  python3 gen_wordlist.py --category familj --id familj --name "Familj" --phrases
  python3 gen_wordlist.py --category familj --id familj --name "Familj" --phrases --ai-bracket
""")
    parser.add_argument("--wordfile", default=None, help="Text file with one word per line (optional if --category used)")
    parser.add_argument("--category", default=None, help="Filter to words in this category slug (comma-separated, from sign_data.csv category_slug col)")
    parser.add_argument("--maxlength", type=int, default=100, help="Maximum number of words (default: 100)")
    parser.add_argument("--id", default=None, help="Wordlist ID (e.g. 'mylist')")
    parser.add_argument("--name", default=None, help="Display name (e.g. 'My List')")
    parser.add_argument("--outdir", default=None, help="Output directory (default: lists/ next to script)")
    parser.add_argument("--csv", default=None, help="Path to sign_data.csv (default: same dir as script)")
    parser.add_argument("--freq", default=None, help="Path to stats_PAROLE.txt (default: same dir as script)")
    parser.add_argument("--no-verify", action="store_true", help="Skip video URL verification")
    parser.add_argument("--list-categories", action="store_true", help="List all categories and exit")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild lists/all.js and exit")
    parser.add_argument("--phrases", action="store_true", help="Embed phrase data in output JS")
    parser.add_argument("--ai-bracket", action="store_true", help="Use Claude Haiku to bracket inflection forms (requires: pip install anthropic + ANTHROPIC_API_KEY)")
    parser.add_argument("--split", type=int, default=None, help="Split into balanced chunks of at most N words; generates {id}1.js, {id}2.js, ...")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = args.csv or os.path.join(script_dir, "sign_data.csv")
    freq_path = args.freq or os.path.join(script_dir, "lists", "stats_PAROLE.txt")

    lists_dir = args.outdir or os.path.join(script_dir, "lists")

    if args.rebuild:
        rebuild_all_js(lists_dir)
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
            slug = row.get("category_slug", "").strip()
            label = row.get("category", "").strip()
            if slug:
                cats[slug] = (label, cats.get(slug, (label, 0))[1] + 1)
        for slug in sorted(cats.keys()):
            label, count = cats[slug]
            print(f"  {slug}  ({label}, {count} words)")
        return

    # Validate required args for generation
    if not args.id or not args.name:
        parser.error("--id and --name are required for generation")

    if not args.wordfile and not args.category:
        parser.error("At least one of --wordfile or --category is required")

    # --- Set up AI client if needed ---
    ai_client = None
    if args.ai_bracket:
        try:
            import anthropic
            ai_client = anthropic.Anthropic()
        except ImportError:
            print("Error: --ai-bracket requires the anthropic package. Run: pip install anthropic", file=sys.stderr)
            sys.exit(1)

    # --- Build candidate words ---

    # Parse comma-separated category slugs
    category_slugs = set()
    if args.category:
        category_slugs = {s.strip().lower() for s in args.category.split(",") if s.strip()}

    has_bok = BOK_SLUG in category_slugs
    other_slugs = category_slugs - {BOK_SLUG}

    # Build word → sign data lookup (word → first matching row)
    word_lookup = {}
    for row in sign_rows:
        word = row["word"].strip().lower()
        slug = row.get("category_slug", "").strip().lower()
        movie = row.get("movie", "").strip()
        if not movie:
            continue
        if category_slugs:
            matches = (has_bok and is_bokstavering_row(row)) or (bool(other_slugs) and slug in other_slugs)
            if not matches:
                continue
        if word not in word_lookup:
            word_lookup[word] = row

    if category_slugs:
        matched_slugs = set()
        for row in sign_rows:
            slug = row.get("category_slug", "").strip().lower()
            if slug and slug in other_slugs:
                matched_slugs.add(slug)
            if has_bok and is_bokstavering_row(row) and row.get("movie", "").strip():
                matched_slugs.add(BOK_SLUG)
        missing = category_slugs - matched_slugs
        if matched_slugs:
            print(f"Category slug(s) matched: {', '.join(sorted(matched_slugs))} ({len(word_lookup)} words)")
        if missing:
            print(f"Warning: category slug(s) not found: {', '.join(sorted(missing))}")

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
                warnings.append(f"NOT FOUND: '{w}'" + (f" (not in category slug(s): {args.category})" if args.category else ""))
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

    # --- Build phrase entries ---

    phrase_entries = []
    if args.phrases:
        for entry in entries:
            word = entry["word"]
            row = word_lookup[word]
            raw_phrases = parse_phrases_column(row.get("phrases", ""))
            for p in raw_phrases:
                phrase_text = p.get("phrase", "").strip()
                movie = p.get("movie", "").strip()
                if not phrase_text or not movie:
                    continue
                # Strip "alt N." prefix
                phrase_text = re.sub(r"^alt\s+\d+\.\s*", "", phrase_text)
                # Collapse whitespace
                phrase_text = re.sub(r"\s+", " ", phrase_text).strip()
                if not phrase_text:
                    continue
                # Apply bracketing
                if ai_client:
                    print(f"  AI-bracket: '{word}' in '{phrase_text[:50]}...'", end=" ", flush=True)
                    phrase_text = ai_bracket(word, phrase_text, ai_client)
                    print("done")
                else:
                    phrase_text = auto_bracket(word, phrase_text)
                video_filename = extract_video_filename(movie)
                phrase_entries.append({"word": word, "phrase": phrase_text, "video": video_filename})

        # Deduplicate by (word, phrase_text) — same text with different videos counts once
        seen_phrases = set()
        unique_phrase_entries = []
        for pe in phrase_entries:
            key = (pe["word"], pe["phrase"])
            if key not in seen_phrases:
                seen_phrases.add(key)
                unique_phrase_entries.append(pe)
        phrase_entries = unique_phrase_entries

    # --- Output JS file(s) ---

    os.makedirs(lists_dir, exist_ok=True)

    if args.split and len(entries) > args.split:
        num_chunks = math.ceil(len(entries) / args.split)
        chunk_size = math.ceil(len(entries) / num_chunks)
        chunks = [entries[i:i + chunk_size] for i in range(0, len(entries), chunk_size)]
        output_paths = []
        for n, chunk in enumerate(chunks, 1):
            chunk_words = {e["word"] for e in chunk}
            chunk_phrases = [pe for pe in phrase_entries if pe["word"] in chunk_words]
            chunk_id = f"{args.id}{n}"
            chunk_name = f"{args.name} {n}"
            out = os.path.join(lists_dir, f"{chunk_id}.js")
            write_wordlist_js(out, chunk_id, chunk_name, chunk, chunk_phrases)
            print(f"  {chunk_name}: {len(chunk)} words, {len(chunk_phrases)} phrases → {out}")
            output_paths.append(out)
        print(f"\nWrote {len(chunks)} lists ({len(entries)} words total)")
        if args.phrases and not args.ai_bracket:
            print('Tip: re-run with --ai-bracket for better inflection detection (e.g. "vill"→"vilja")')
        try:
            if os.path.samefile(os.path.dirname(os.path.abspath(output_paths[0])), lists_dir):
                rebuild_all_js(lists_dir)
        except FileNotFoundError:
            pass
    else:
        output_path = os.path.join(lists_dir, f"{args.id}.js")
        write_wordlist_js(output_path, args.id, args.name, entries, phrase_entries)
        print(f"\nWrote {len(entries)} words to {output_path}")
        if args.phrases:
            print(f"Embedded {len(phrase_entries)} phrase entries")
            if not args.ai_bracket:
                print('Tip: re-run with --ai-bracket for better inflection detection (e.g. "vill"→"vilja")')
        try:
            if os.path.samefile(os.path.dirname(os.path.abspath(output_path)), lists_dir):
                rebuild_all_js(lists_dir)
        except FileNotFoundError:
            pass

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(f"  {w}")

    if len(entries) == 0:
        print("\nNo valid entries generated!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
