# stringgy.py — binary-safe string search & in-place edit tool thing

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
