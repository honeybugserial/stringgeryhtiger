# stringgy.py — binary-safe string search & in-place edit (Windows-friendly)

Scan binaries for a substring (UTF-8, UTF-16LE, optional UTF-16BE), show the **full decoded context**, and interactively **patch** selected matches in place. No byte shifting. Backups are automatic and timestamped.

> ⚠️ This edits files in place. If you don’t know what you’re changing, don’t. Changing effective string lengths can break binaries. Prefer equal-length replacements unless you’re sure.

## Features

- Find substrings encoded as **UTF-8** and **UTF-16LE** (optionally **UTF-16BE**).
- Print each hit with **file offset** (hex + dec), **encoding**, **exact bytes**, and **full context** (expanded to NUL/non-printable boundaries).
- **Interactive editor**:
  - Pick a match (index), enter a new string, see a **preview** of the result, confirm, then write.
  - Modes for length mismatch: `exact`, `padnul`, `padspace` (custom pad char), `truncate`.
  - **Verification** after write (re-reads bytes and confirms).
- **Batch replace** with mode control.
- **Backups** always created: `file.YYYYMMDD-HHMMSS.bak` (auto `-1`, `-2` suffixes if needed).
- **Windows-friendly**; colors via `colorama`.

## Install

```bash
pip install colorama
```

Python 3.8+.

## Quick start

Search only:

```bash
python stringgy.py --input Proxifier.exe --search proxifier.com
```

Interactive edit (same as above; you’ll be prompted after the list):

```bash
python stringgy.py --input Proxifier.exe --search proxifier.com --interactive
```

Batch replace **all** (equal length only):

```bash
python stringgy.py --input Proxifier.exe --search proxifier.com \
  --replace proxifier.net --mode exact --all --yes
```

## Example (interactive single-edit)

```
[13] Match at 0x0036E518 (3597592)
  Encoding   : utf-16le
  Exact bytes: b'p\x00r\x00o\x00x\x00i\x00f\x00i\x00e\x00r\x00.\x00c\x00o\x00m\x00'
  Context    : https://www.proxifier.com/docs/win-v4/

Backup created: .\Proxifier.exe.20250916-173229.bak
Edit which index? (e.g., 12, 'all', or 'q' to quit): 13
[13] Editing 0x0036E518  enc=utf-16le
OLD Context: https://www.proxifier.com/docs/win-v4/
Exact bytes: b'p\x00r\x00o\x00x\x00i\x00f\x00i\x00e\x00r\x00.\x00c\x00o\x00m\x00'
NEW string for this match: poooooooo.poo
— EDIT REVIEW —
Old context : https://www.proxifier.com/docs/win-v4/
Mode=exact | old_len=26 | new_in_len=26 | write_len=26
Preview     : https://www.pooooooo.poo/docs/win-v4/
Write this change? [y/N]: y
OK: verified bytes @ 0x0036E518
```

## CLI

```
usage: stringgy.py --input PATH --search TEXT [options]

Search:
  --input PATH         File to scan
  --search TEXT        Substring to find
  --ignore-case        Case-insensitive (ASCII only)
  --utf16be            Also search UTF-16BE
  --limit N            Show only first N hits
  --interactive        Force interactive edit loop after listing

Batch replace:
  --replace NEWSTR     Enable batch replace
  --mode {exact,padnul,padspace,truncate}
  --all                Apply to all matches
  --yes                Auto-confirm "Replace ALL?" prompt
  --pad-char CH        Pad char for padspace (default: space)

Other:
  (Backups are always created; named with timestamp + numeric suffix if needed)
```

### Modes (when lengths differ)

- `exact` — only if new length == old length. Safest.
- `padnul` — shorter new string padded with NULs (`\x00` or `\x00\x00` for UTF-16).
- `padspace` — shorter new string padded with spaces or a custom single char (`--pad-char`).
- `truncate` — longer new string cut to fit the original byte span.

## How it works (short version)

- Reads the file with `mmap`.
- Encodes the search term as UTF-8 and UTF-16LE (and optionally UTF-16BE) and finds **all** matches.
- Expands context outward until hitting a strong boundary (NUL or a short run of non-printables).
- For edits, it **never shifts bytes**; it overwrites the matched span only. If lengths don’t match, you choose padding/truncation.
- On write: previews, prompts, writes, **verifies bytes**, done.

## Safety & limitations

- **No shifting or reallocation.** This is intentional to avoid corrupting PE offsets/resources.
- **Case-insensitive** search is ASCII-oriented (byte `.lower()`); if you need full Unicode case-folding, this tool doesn’t do it.
- **UTF-16** assumes aligned 2-byte code units; surrogate handling is not decoded into code points (good enough for plain ASCII/latin URLs and text).
- Padding **spaces** become part of the string. If a consumer uses the text verbatim (e.g., URLs), trailing spaces can break behavior. You’ll see the preview before committing.
- You’re responsible for what you patch. Keep backups.

## Troubleshooting

- “Nothing changed.” — You probably answered `N` at the final **Write this change?** prompt, or picked an incompatible mode. Try equal length, `padspace`, or `truncate` as appropriate.
- “Verify failed.” — The write didn’t match expected bytes (file locked, AV interference, or race). Close other tools, retry.
- “Pad char error.” — Your pad char must be **one** character and its encoded byte length must divide the pad gap (true for ASCII/space).

## Contributing

Keep it simple:
- No external deps beyond `colorama`.
- No byte shifting or PE rewriting.
- PRs that add clarity to the interactive flow, verification, or safety checks are welcome.

## License

Add whatever license you want for your repo (MIT/Apache-2.0/etc.).
