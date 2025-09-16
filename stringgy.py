#!/usr/bin/env python3
# stringgy.py
# Search UTF-8/UTF-16 strings in a binary, print full context with color,
# and interactively replace chosen matches (or batch replace by flags).
"""
stringgy.py — binary-safe string search & in-place edit (Windows-friendly)

WHAT IT DOES
- Scans a file for a substring encoded as UTF-8 and UTF-16LE (optionally UTF-16BE).
- Prints every match with:
  • file offset (hex + decimal)
  • encoding
  • exact matched bytes
  • FULL decoded context (expanded to NUL / non-printable boundaries)
- Interactive editor:
  • Pick a match (by index), enter a new string, see a PREVIEW of the result,
    confirm [y/N], then it writes in place and verifies bytes at that offset.
- Replace modes when lengths differ:
  • exact     – only if new == old length (safest)
  • padnul    – shorter new string padded with NULs (0x00 / 0x00 0x00)
  • padspace  – shorter new string padded with spaces (or a custom char)
  • truncate  – longer new string cut to fit
- Backups are ALWAYS created before any write:
  • `<filename>.<YYYYMMDD-HHMMSS>.bak`, and if that exists, `...-1`, `...-2`, ...

REQUIREMENTS
- Python 3.8+
- `colorama` (colors):     pip install colorama
- `rich` (splash screen):  pip install rich

BASIC USAGE (SEARCH / LIST)
    python stringgy.py --input programtool.exe --search example.com
Options:
    --ignore-case        Case-insensitive search
    --utf16be            Also search UTF-16BE (in addition to UTF-8/UTF-16LE)
    --limit N            Show only the first N hits

INTERACTIVE EDIT (DEFAULT when you don’t pass --replace)
    python stringgy.py --input programtool.exe --search example.com
    # or explicitly:
    python stringgy.py --input programtool.exe --search example.com --interactive

BATCH REPLACE (non-interactive selection; still shows per-write preview/confirm)
Replace ALL matches with the same string and chosen mode:
    python stringgy.py --input programtool.exe --search example.com \
        --replace example.org --mode exact --all --yes
Notes:
  - `--mode` is required in batch: exact | padnul | padspace | truncate
  - `--yes` auto-confirms the “Replace ALL?” prompt, but each write still shows
    a preview and asks to confirm (by design, to prevent accidental mass edits).
Replace a subset (you’ll be prompted to enter indices like "1,3-5"):
    python stringgy.py --input programtool.exe --search example.com \
        --replace example.org --mode padspace

SAFETY NOTES (read this)
- This is an in-place editor. It NEVER shifts bytes; it only overwrites the
  exact matched span. Changing effective string lengths can break binaries.
  If you aren’t sure, use same-length replacements (mode: exact).
- `padspace` adds trailing spaces to fill the gap. That may break URLs or
  signatures if the consumer doesn’t trim. You’ll see the preview before writing.
- Verification: after each write, the script re-reads the file and confirms the
  exact bytes at that offset match what was intended. If verification fails, it
  warns you immediately.
- Backups: always created with a timestamped name; if one exists for that
  second, a numeric suffix is added. Keep these if you need to roll back.

TIPS
- To replace “example.com” with an equal-length string in UTF-16LE, keep the
  same number of characters (each BMP char = 2 bytes).
- To quickly sanity-check your change, run another search for your NEW string.
- If you don’t see a change, you probably declined the final [y/N] prompt or
  picked an incompatible mode for the length difference.

EXAMPLES
List hits only:
    python stringgy.py --input programtool.exe --search example.com
Edit a single hit interactively (e.g., index 13), pad with spaces if shorter:
    python stringgy.py --input programtool.exe --search example.com
    # then at the prompt: 13 → enter new string → choose padspace
Batch replace all with exact length:
    python stringgy.py --input programtool.exe --search example.com \
        --replace example.net --mode exact --all --yes
Batch replace all with space padding when shorter (custom pad char “_”):
    python stringgy.py --input programtool.exe --search example.com \
        --replace example.io --mode padspace --all --yes --pad-char _
Also search UTF-16BE and ignore case:
    python stringgy.py --input programtool.exe --search ExAmPlE.CoM --utf16be --ignore-case
"""

import argparse, mmap, os, sys, re, shutil, time
from typing import Optional
from colorama import init, Fore, Style
init(autoreset=True)

# ---- Splash (clears → shows → waits 2s → clears) ----
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich import box
    _console = Console()
    def show_splash():
        _console.clear()
        ascii_logo = r"""
  __| __ __| _ \ _ _|   \ |   __|   __| \ \  / _ \ \ \  /
\__ \    |     /   |   .  |  (_ |  (_ |  \  /    /  \  /
____/   _|  _|_\ ___| _|\_| \___| \___|   _|  _|_\   _|
__ __| |  | _ _|   \ |   __| \ \  /
   |   __ |   |   .  |  (_ |  \  /
  _|  _| _| ___| _|\_| \___|   _|
"""
        _console.print(
            Panel.fit(
                ascii_logo,
                title="stringrery thinggy script",
                title_align="center",
                border_style="bold cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        time.sleep(2.0)
        _console.clear()
except Exception:
    # Fallback if 'rich' not installed – minimal splash
    def show_splash():
        os.system("cls" if os.name == "nt" else "clear")
        print("=== stringrery thinggy script ===")
        time.sleep(2.0)
        os.system("cls" if os.name == "nt" else "clear")

PRINTABLE_UTF8 = set(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}

def find_all(hay: bytes, needle: bytes, step: int = 1):
    if not needle: return
    i = 0
    while True:
        i = hay.find(needle, i)
        if i < 0: return
        yield i
        i += step

def _is_printable_byte(b: int) -> bool:
    return b in PRINTABLE_UTF8

# ---------- Context expansion (and bounds helpers) ----------
def bounds_utf8(mm: mmap.mmap, start: int, end: int):
    L = len(mm); left = start; right = end
    bad_run = 0
    while left > 0:
        x = mm[left-1]
        if x == 0x00: break
        if not _is_printable_byte(x):
            bad_run += 1
            if bad_run >= 3: break
        else: bad_run = 0
        left -= 1
    bad_run = 0
    while right < L:
        x = mm[right]
        if x == 0x00: break
        if not _is_printable_byte(x):
            bad_run += 1
            if bad_run >= 3: break
        else: bad_run = 0
        right += 1
    return left, right

def _bounds_utf16(mm: mmap.mmap, start: int, end: int, be: bool):
    L = len(mm); left = start; right = end
    def get_u16(idx):
        if idx < 0 or idx+1 >= L: return None
        return (mm[idx]<<8 | mm[idx+1]) if be else (mm[idx] | (mm[idx+1]<<8))
    if left % 2: left -= 1
    if right % 2: right += 1
    bad_run = 0
    while left-2 >= 0:
        code = get_u16(left-2)
        if code is None or code == 0x0000: break
        if 0x20 <= code <= 0x7E or code in (0x09,0x0A,0x0D) or (0xA0 <= code <= 0x10FFFF):
            bad_run = 0
        else:
            bad_run += 1
            if bad_run >= 2: break
        left -= 2
    bad_run = 0
    while right+2 <= L:
        code = get_u16(right)
        if code is None or code == 0x0000: break
        if 0x20 <= code <= 0x7E or code in (0x09,0x0A,0x0D) or (0xA0 <= code <= 0x10FFFF):
            bad_run = 0; right += 2
        else:
            bad_run += 1
            if bad_run >= 2: break
            right += 2
    return left, right

def expand_full_utf8(mm: mmap.mmap, start: int, end: int) -> bytes:
    l, r = bounds_utf8(mm, start, end)
    return bytes(mm[l:r])

def expand_full_utf16le(mm: mmap.mmap, start: int, end: int) -> bytes:
    l, r = _bounds_utf16(mm, start, end, be=False)
    return bytes(mm[l:r])

def expand_full_utf16be(mm: mmap.mmap, start: int, end: int) -> bytes:
    l, r = _bounds_utf16(mm, start, end, be=True)
    return bytes(mm[l:r])

# ---------- UI helpers ----------
from colorama import init as _dummy  # keep colorama import alive for packaging
def color_highlight(text: str, needle: str, ignore_case: bool) -> str:
    flags = re.IGNORECASE if ignore_case else 0
    pattern = re.compile(re.escape(needle), flags)
    return pattern.sub(lambda m: Fore.YELLOW + Style.BRIGHT + m.group(0) + Style.RESET_ALL, text)

def decode_safe(b: bytes, encoding: str) -> str:
    try: return b.decode(encoding, errors="replace")
    except Exception: return repr(b)

# ---------- Search ----------
def search(path: str, term: str, include_utf16be: bool, ignore_case: bool):
    results = []
    with open(path, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        t8 = term.encode('utf-8')
        t16le = term.encode('utf-16-le')
        t16be = term.encode('utf-16-be') if include_utf16be else None
        def find_ci(hay: bytes, needle: bytes, step: int):
            n = len(needle); nl = needle.lower(); i = 0; L = len(hay)
            while i <= L - n:
                if hay[i:i+n].lower() == nl: yield i; i += step
                else: i += step
        # UTF-8
        offs = list(find_ci(mm, t8, 1)) if ignore_case else list(find_all(mm, t8, 1))
        for off in offs:
            results.append({"offset": off, "enc": "utf-8",
                            "match_bytes": bytes(mm[off:off+len(t8)]),
                            "full_bytes": expand_full_utf8(mm, off, off+len(t8)),
                            "term_bytes": t8})
        # UTF-16LE
        offs = list(find_ci(mm, t16le, 2)) if ignore_case else list(find_all(mm, t16le, 2))
        for off in offs:
            results.append({"offset": off, "enc": "utf-16le",
                            "match_bytes": bytes(mm[off:off+len(t16le)]),
                            "full_bytes": expand_full_utf16le(mm, off, off+len(t16le)),
                            "term_bytes": t16le})
        # UTF-16BE
        if t16be:
            offs = list(find_ci(mm, t16be, 2)) if ignore_case else list(find_all(mm, t16be, 2))
            for off in offs:
                results.append({"offset": off, "enc": "utf-16be",
                                "match_bytes": bytes(mm[off:off+len(t16be)]),
                                "full_bytes": expand_full_utf16be(mm, off, off+len(t16be)),
                                "term_bytes": t16be})
    return results

def encode_by_enc(s: str, enc: str) -> bytes:
    if enc == "utf-8": return s.encode("utf-8")
    if enc == "utf-16le": return s.encode("utf-16-le")
    if enc == "utf-16be": return s.encode("utf-16-be")
    raise ValueError("unknown encoding")

def pad_bytes(enc: str, pad_char: str, nbytes: int) -> bytes:
    if not pad_char or len(pad_char) != 1:
        raise ValueError("pad_char must be a single character")
    unit = pad_char.encode(enc)
    ulen = len(unit)
    if nbytes % ulen != 0:
        raise ValueError(f"pad gap {nbytes} is not a multiple of encoded pad length {ulen}")
    return unit * (nbytes // ulen)

def fmt_and_show_hits(hits, needle, ignore_case):
    if not hits:
        print(Fore.YELLOW + "No matches found." + Style.RESET_ALL); return
    hits.sort(key=lambda h: h["offset"])
    for idx, h in enumerate(hits, 1):
        off = h["offset"]; enc = h["enc"]
        exact = h["match_bytes"]; full = h["full_bytes"]
        print(Fore.CYAN + f"[{idx}] Match at 0x{off:08X} ({off})" + Style.RESET_ALL)
        print(f"  Encoding   : {Fore.GREEN}{enc}{Style.RESET_ALL}")
        print(f"  Exact bytes: {Fore.MAGENTA}{exact!r}{Style.RESET_ALL}")
        ctx = decode_safe(full, "utf-8" if enc=="utf-8" else ("utf-16-le" if enc=="utf-16le" else "utf-16-be"))
        print("  Context    : " + color_highlight(ctx, needle, ignore_case)); print()

# ---------- Backups (timestamp + numeric suffix) ----------
def unique_backup_name(path: str) -> str:
    base = f"{path}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
    if not os.path.exists(base):
        return base
    n = 1
    while True:
        cand = f"{base}-{n}"
        if not os.path.exists(cand):
            return cand
        n += 1

def ensure_backup(path):
    bak = unique_backup_name(path)
    shutil.copy2(path, bak)
    print(Fore.WHITE + f"Backup created: {bak}" + Style.RESET_ALL)
    return bak

# ---------- Write + preview + verify ----------
def adjusted_write_bytes(enc: str, new_str: str, old_len: int, mode: str, pad_char: str = ' ') -> Optional[bytes]:
    nb = encode_by_enc(new_str, enc)
    if len(nb) == old_len:
        return nb
    if mode == "padnul" and len(nb) < old_len:
        unit = b"\x00" if enc == "utf-8" else b"\x00\x00"
        if (old_len - len(nb)) % len(unit) != 0: return None
        return nb + unit * ((old_len - len(nb)) // len(unit))
    if mode == "padspace" and len(nb) < old_len:
        try:
            return nb + pad_bytes(enc, pad_char, old_len - len(nb))
        except Exception:
            return None
    if mode == "truncate" and len(nb) > old_len:
        return nb[:old_len]
    if mode == "exact":
        return None
    return None

def build_preview_text(path, hit, written_bytes):
    enc = hit["enc"]; off = hit["offset"]; old_len = len(hit["term_bytes"])
    with open(path, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        if enc == "utf-8":
            l, r = bounds_utf8(mm, off, off+old_len)
            preview_bytes = bytes(mm[l:off]) + written_bytes + bytes(mm[off+old_len:r])
            dec = 'utf-8'
        elif enc == "utf-16le":
            l, r = _bounds_utf16(mm, off, off+old_len, be=False)
            preview_bytes = bytes(mm[l:off]) + written_bytes + bytes(mm[off+old_len:r])
            dec = 'utf-16-le'
        else:
            l, r = _bounds_utf16(mm, off, off+old_len, be=True)
            preview_bytes = bytes(mm[l:off]) + written_bytes + bytes(mm[off+old_len:r])
            dec = 'utf-16-be'
    return decode_safe(preview_bytes, dec)

def verify_bytes(path, off, expected: bytes) -> bool:
    with open(path, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        return mm[off:off+len(expected)] == expected

def write_one(path, hit, new_str, mode, pad_char=' '):
    enc = hit["enc"]; off = hit["offset"]; old_len = len(hit["term_bytes"])
    eff = adjusted_write_bytes(enc, new_str, old_len, mode, pad_char)
    if eff is None:
        print(Fore.RED + f"Cannot write @ 0x{off:08X}: incompatible lengths for mode '{mode}'." + Style.RESET_ALL)
        return False
    old_ctx = decode_safe(hit["full_bytes"], "utf-8" if enc=="utf-8" else ("utf-16-le" if enc=="utf-16le" else "utf-16-be"))
    new_ctx = build_preview_text(path, hit, eff)
    print(Fore.BLUE + "— EDIT REVIEW —" + Style.RESET_ALL)
    print("Old context : " + old_ctx)
    print(Fore.YELLOW + f"Mode={mode} | old_len={old_len} | new_in_len={len(encode_by_enc(new_str, enc))} | write_len={len(eff)}" + Style.RESET_ALL)
    print("Preview     : " + new_ctx)
    confirm = input(Fore.YELLOW + "Write this change? [y/N]: " + Style.RESET_ALL).strip().lower()
    if confirm not in ("y","yes"):
        print("Skipped.")
        return False
    with open(path, "r+b") as f, mmap.mmap(f.fileno(), 0) as mm:
        mm[off:off+old_len] = eff
        mm.flush()
    ok = verify_bytes(path, off, eff)
    if ok:
        print(Fore.GREEN + f"OK: verified bytes @ 0x{off:08X}" + Style.RESET_ALL)
    else:
        print(Fore.RED + f"WARNING: verify failed @ 0x{off:08X}" + Style.RESET_ALL)
    return ok

# ---------- Interactive loop ----------
def interactive_loop(path, hits, search_str, ignore_case, default_mode="exact", default_pad_char=' '):
    if not hits:
        print(Fore.YELLOW + "No matches to edit." + Style.RESET_ALL); return
    ensure_backup(path)
    while True:
        sel = input(Fore.CYAN + "Edit which index? (e.g., 69, 'all', or 'q' to quit): " + Style.RESET_ALL).strip().lower()
        if sel in ("q","quit","exit"): break
        if sel in ("all","*","a"):
            new_str = input(Fore.WHITE + "NEW string for ALL matches: " + Style.RESET_ALL)
            if not new_str: print("Empty new string. Skipped."); continue
            mode = input(Fore.YELLOW + f"Mode [exact/padnul/padspace/truncate] (default {default_mode}): " + Style.RESET_ALL).strip().lower() or default_mode
            if mode not in ("exact","padnul","padspace","truncate"):
                print("Invalid mode."); continue
            pad_char = default_pad_char
            if mode == "padspace":
                tmp = input(Fore.YELLOW + f"Pad char (single char, default space): " + Style.RESET_ALL)
                if tmp: pad_char = tmp[0]
            wrote = 0
            for h in hits:
                wrote += 1 if write_one(path, h, new_str, mode, pad_char=pad_char) else 0
            print(Fore.WHITE + Style.BRIGHT + f"Done. Replacements written: {wrote}/{len(hits)}" + Style.RESET_ALL)
            continue

        try:
            i = int(sel)
        except ValueError:
            print("Invalid input."); continue
        if not (1 <= i <= len(hits)):
            print("Out of range."); continue

        h = hits[i-1]
        enc = h["enc"]; off = h["offset"]; full = h["full_bytes"]
        ctx = decode_safe(full, "utf-8" if enc=="utf-8" else ("utf-16-le" if enc=="utf-16le" else "utf-16-be"))
        print(Fore.CYAN + f"[{i}] Editing 0x{off:08X}  enc={enc}" + Style.RESET_ALL)
        print("OLD Context: " + color_highlight(ctx, search_str, ignore_case))
        print(f"Exact bytes: {Fore.MAGENTA}{h['match_bytes']!r}{Style.RESET_ALL}")

        new_str = input(Fore.WHITE + "NEW string for this match: " + Style.RESET_ALL)
        if not new_str:
            print("Empty new string. Skipped.")
            continue

        in_len = len(encode_by_enc(new_str, enc))
        old_len = len(h["term_bytes"])

        if in_len == old_len:
            write_one(path, h, new_str, "exact")
        elif in_len < old_len:
            print(Fore.YELLOW + f"Shorter by {old_len - in_len} byte(s). Choose pad mode." + Style.RESET_ALL)
            print("  [N] Pad with NULs   [S] Pad with spaces/custom   [E] Exact (skip)")
            ch = input("Mode (N/S/E)? ").strip().lower()
            if ch == "n":
                write_one(path, h, new_str, "padnul")
            elif ch == "s":
                tmp = input("Pad char (single char, default space): ").strip()
                pad_char = tmp[0] if tmp else ' '
                write_one(path, h, new_str, "padspace", pad_char=pad_char)
            else:
                print("Skipped.")
        else:
            print(Fore.YELLOW + f"Longer by {in_len - old_len} byte(s). Options: [T]runcate or [E]xact (skip)" + Style.RESET_ALL)
            ch = input("Mode (T/E)? ").strip().lower()
            if ch == "t":
                write_one(path, h, new_str, "truncate")
            else:
                print("Skipped.")

# ---------- Batch helper ----------
def replace_batch(path, hits, new_str, indices, mode, pad_char=' '):
    if not hits or not indices: return 0
    ensure_backup(path)
    written = 0
    for i in sorted(indices):
        h = hits[i-1]
        if write_one(path, h, new_str, mode, pad_char=pad_char): written += 1
    return written

def parse_selection(sel_text, count):
    sel_text = sel_text.strip().lower()
    if sel_text in ("all","a","*"): return list(range(1, count+1))
    out = set()
    for part in sel_text.split(","):
        part = part.strip()
        if not part: continue
        if "-" in part:
            a,b = part.split("-",1)
            try:
                a = int(a); b = int(b)
                if a > b: a,b = b,a
                for i in range(a, b+1):
                    if 1 <= i <= count: out.add(i)
            except: pass
        else:
            try:
                i = int(part)
                if 1 <= i <= count: out.add(i)
            except: pass
    return sorted(out)

def main():
    show_splash()  # <--- clear → splash → 2s → clear
    ap = argparse.ArgumentParser(description="Search a file for a string (UTF-8/UTF-16), full-context output, interactive replace with preview & verify.")
    ap.add_argument("--input", required=True, help="Path to input file")
    ap.add_argument("--search", required=True, help="Search string (substring match)")
    ap.add_argument("--utf16be", action="store_true", help="Also search UTF-16BE")
    ap.add_argument("--ignore-case", action="store_true", help="Case-insensitive search")
    ap.add_argument("--limit", type=int, default=0, help="Max matches to print (0 = all)")
    # batch replace options
    ap.add_argument("--replace", metavar="NEWSTR", help="Batch replace mode with NEWSTR")
    ap.add_argument("--all", action="store_true", help="Replace all matches in batch mode")
    ap.add_argument("--yes", action="store_true", help="Assume 'yes' for prompts in batch mode")
    ap.add_argument("--no-backup", action="store_true", help="(ignored) Backups always created with timestamp")
    ap.add_argument("--interactive", action="store_true", help="Force interactive edit loop after listing")
    ap.add_argument("--mode", choices=["exact","padnul","padspace","truncate"], help="Batch replace mode")
    ap.add_argument("--pad-char", default=" ", help="Pad character for padspace (single char). Default: space")
    args = ap.parse_args()

    path = args.input
    if not os.path.isfile(path):
        print(f"{Fore.RED}Error: '{path}' not found.{Style.RESET_ALL}"); sys.exit(1)

    hits = search(path, args.search, args.utf16be, args.ignore_case)
    if args.limit and args.limit > 0 and len(hits) > args.limit:
        hits = sorted(hits, key=lambda h: h["offset"])[:args.limit]

    fmt_and_show_hits(hits, args.search, args.ignore_case)
    if not hits: return

    # Batch mode
    if args.replace:
        if not (args.mode):
            print(Fore.RED + "Specify --mode exact|padnul|padspace|truncate for batch replacement." + Style.RESET_ALL)
            return
        if args.all:
            if not args.yes:
                confirm = input(Fore.YELLOW + f"Replace ALL {len(hits)} matches with '{args.replace}' using [{args.mode}]? [y/N]: " + Style.RESET_ALL).strip().lower()
                if confirm not in ("y","yes"): print("Aborted."); return
            wrote = replace_batch(path, hits, args.replace, list(range(1, len(hits)+1)), args.mode, pad_char=args.pad_char[:1])
            print(Fore.WHITE + Style.BRIGHT + f"Replacements written: {wrote}/{len(hits)}" + Style.RESET_ALL)
        else:
            if args.yes:
                print(Fore.RED + "Batch mode without --all does nothing with --yes. Use --interactive or provide indices." + Style.RESET_ALL)
                return
            sel = input(Fore.CYAN + f"Select match indices to replace (e.g., 1,3-5 or 'all'): " + Style.RESET_ALL)
            idxs = parse_selection(sel, len(hits))
            if not idxs: print("No valid selection. Aborted."); return
            wrote = replace_batch(path, hits, args.replace, idxs, args.mode, pad_char=args.pad_char[:1])
            print(Fore.WHITE + Style.BRIGHT + f"Replacements written: {wrote}/{len(idxs)}" + Style.RESET_ALL)
        return

    # Interactive
    interactive_loop(path, hits, args.search, args.ignore_case)

if __name__ == "__main__":
    main()
