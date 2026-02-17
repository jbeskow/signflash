#!/usr/bin/env python3
"""Generate phrases.js from wordlist.js + phrases.csv."""

import csv
import json
import re
import sys

def main():
    # 1. Extract word→ID mapping from wordlist.js
    with open("wordlist.js", encoding="utf-8") as f:
        wordlist_text = f.read()

    # Match entries like: { word: "björn", video: "bjorn-00010-tecken.mp4" }
    entries = re.findall(
        r'\{\s*word:\s*"([^"]+)",\s*video:\s*"[^"]*?-(\d{5})-tecken\.mp4"\s*\}',
        wordlist_text,
    )
    id_to_word = {}
    for word, vid_id in entries:
        id_to_word[vid_id] = word

    print(f"Found {len(id_to_word)} words in wordlist.js", file=sys.stderr)

    # 2. Read phrases.csv and match by ID
    phrases = []
    seen_videos = set()
    skipped = 0
    with open("phrases.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            movie = row.get("movie", "").strip()
            phrase_text = row.get("phrase", "").strip()
            csv_word = row.get("word", "").strip()

            if not movie or not phrase_text:
                skipped += 1
                continue

            # Skip multi-word entries
            if " " in csv_word:
                skipped += 1
                continue

            # Extract 5-digit ID from movie filename
            m = re.search(r"-(\d{5})-fras-", movie)
            if not m:
                skipped += 1
                continue

            vid_id = m.group(1)
            if movie in seen_videos:
                skipped += 1
                continue
            seen_videos.add(movie)
            if vid_id not in id_to_word:
                skipped += 1
                continue

            # Clean up phrase: remove leading "alt N." prefixes, collapse whitespace
            phrase_text = re.sub(r"^alt\s*\d+\.\s*", "", phrase_text)
            phrase_text = re.sub(r"\s+", " ", phrase_text).strip()

            if not phrase_text:
                skipped += 1
                continue

            # Auto-bracket the keyword form in the phrase
            word = id_to_word[vid_id]
            escaped = re.escape(word)
            phrase_text = re.sub(
                rf"(?<!\[)({escaped}\w*)",
                r"[\1]",
                phrase_text,
                flags=re.IGNORECASE,
            )

            phrases.append({
                "word": word,
                "phrase": phrase_text,
                "video": movie,
            })

    print(f"Generated {len(phrases)} phrases, skipped {skipped} rows", file=sys.stderr)

    # 3. Write phrases.js
    lines = ["const PHRASELIST = ["]
    for p in phrases:
        word_js = json.dumps(p["word"], ensure_ascii=False)
        phrase_js = json.dumps(p["phrase"], ensure_ascii=False)
        video_js = json.dumps(p["video"], ensure_ascii=False)
        lines.append(f"  {{ word: {word_js}, phrase: {phrase_js}, video: {video_js} }},")
    lines.append("];")
    lines.append("")

    with open("phrases.js", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("Wrote phrases.js", file=sys.stderr)


if __name__ == "__main__":
    main()
