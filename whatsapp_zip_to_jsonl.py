#!/usr/bin/env python3
"""
whatsapp_zip_to_jsonl.py
------------------------
Convert a WhatsApp chat export ZIP into normalized JSONL.

Usage:
  python whatsapp_zip_to_jsonl.py --zip /path/to/export.zip --out /path/to/output.jsonl --tz America/Toronto

Features:
- Handles common WhatsApp TXT formats inside the ZIP (iOS/Android).
- Parses multiple date formats (12/24 hour, 2- or 4-digit years, US or Intl ordering).
- Supports en dash or hyphen in headers.
- Preserves multi-line messages by joining until the next header.
- Marks system messages (no sender) vs user messages.
- Adds timezone info to timestamps if tz provided (default America/Toronto).

No third-party dependencies (uses standard library only).
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import re
import sys
import zipfile
from dataclasses import dataclass, asdict
from typing import Iterator, Optional, List, Tuple
from datetime import datetime

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

# Common WhatsApp timestamp layouts
TIMESTAMP_PATTERNS = [
    ("%m/%d/%y, %H:%M",),
    ("%d/%m/%y, %H:%M",),
    ("%m/%d/%Y, %H:%M",),
    ("%d/%m/%Y, %H:%M",),
    ("%m/%d/%y, %I:%M %p",),
    ("%d/%m/%y, %I:%M %p",),
    ("%m/%d/%Y, %I:%M %p",),
    ("%d/%m/%Y, %I:%M %p",),
]

# WhatsApp header: "DATE, TIME - Sender: Message" or "DATE, TIME - System message"
HEADER_RE = re.compile(
    r"""^\s*
    (?P<datetime>[^-]+?)                # datetime portion up to a dash
    \s[-–]\s                            # dash or en dash, surrounded by spaces
    (?P<rest>.*)$                       # remainder: 'Sender: Message' OR system text
    """,
    re.VERBOSE,
)


@dataclass
class NormalizedMessage:
    chat_id: str
    message_id: str
    timestamp: str  # ISO 8601 (with TZ if available)
    sender: Optional[str]
    text: str
    attachments: List[str]
    is_system: bool


def parse_datetime(dt_str: str, tz_name: Optional[str]) -> Optional[datetime]:
    dt_str = re.sub(r"\s+", " ", dt_str.strip())
    for (fmt,) in TIMESTAMP_PATTERNS:
        try:
            ts = datetime.strptime(dt_str, fmt)
            if tz_name and ZoneInfo is not None:
                try:
                    ts = ts.replace(tzinfo=ZoneInfo(tz_name))
                except Exception:
                    # Fallback to naive on TZ failure
                    pass
            return ts
        except Exception:
            continue
    return None


def iter_messages(lines: Iterator[str], tz_name: Optional[str]) -> Iterator[Tuple[datetime, Optional[str], str, bool]]:
    current_ts: Optional[datetime] = None
    current_sender: Optional[str] = None
    current_text_parts: List[str] = []
    current_is_system: bool = False

    def flush():
        nonlocal current_ts, current_sender, current_text_parts, current_is_system
        if current_ts is not None:
            yield (current_ts, current_sender, "\n".join(current_text_parts).rstrip("\n"), current_is_system)
        current_ts = None
        current_sender = None
        current_text_parts = []
        current_is_system = False

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        m = HEADER_RE.match(line)
        if m:
            # Found a new header → flush previous
            yield from flush()
            dt_part = m.group("datetime").strip()
            rest = m.group("rest").strip()

            ts = parse_datetime(dt_part, tz_name)
            if ts is None:
                # Not actually a header; treat as continuation
                if current_ts is not None:
                    current_text_parts.append(line)
                continue

            # Determine sender vs system
            if ":" in rest:
                sender, text = rest.split(":", 1)
                sender = sender.strip() or None
                text = text.lstrip()
                is_system = False
            else:
                sender = None
                text = rest
                is_system = True

            current_ts = ts
            current_sender = sender
            current_text_parts = [text]
            current_is_system = is_system
        else:
            # Continuation line
            if current_ts is not None:
                current_text_parts.append(line)
            # else: ignore until a header is found
    # Flush tail
    yield from flush()


def parse_chat_txt(content: str, tz_name: Optional[str]) -> Iterator[Tuple[datetime, Optional[str], str, bool]]:
    # Strip BOM if present
    if content.startswith("\ufeff"):
        content = content[1:]
    return iter_messages(iter(content.splitlines(True)), tz_name)


def process_zip(zip_path: Path, out_path: Path, tz_name: Optional[str] = "America/Toronto") -> int:
    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf, out_path.open("w", encoding="utf-8") as out_f:
        for info in zf.infolist():
            if not info.filename.lower().endswith(".txt"):
                continue
            chat_id = Path(info.filename).stem
            with zf.open(info, "r") as f:
                raw = f.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")

            for i, (ts, sender, text_msg, is_system) in enumerate(parse_chat_txt(text, tz_name), start=1):
                msg = NormalizedMessage(
                    chat_id=chat_id,
                    message_id=f"{chat_id}:{i}",
                    timestamp=ts.isoformat(),
                    sender=sender,
                    text=text_msg,
                    attachments=[],  # Media mapping is out of scope for Phase 1
                    is_system=is_system,
                )
                out_f.write(json.dumps(asdict(msg), ensure_ascii=False) + "\n")
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="Convert a WhatsApp export ZIP to normalized JSONL.")
    parser.add_argument("--zip", required=True, help="Path to WhatsApp export .zip")
    parser.add_argument("--out", required=True, help="Output JSONL path")
    parser.add_argument("--tz", default="America/Toronto", help="IANA timezone (default: America/Toronto)")
    args = parser.parse_args()

    zip_path = Path(args.zip)
    out_path = Path(args.out)

    if not zip_path.exists():
        print(f"Error: ZIP not found: {zip_path}", file=sys.stderr)
        sys.exit(1)

    try:
        n = process_zip(zip_path, out_path, args.tz)
    except zipfile.BadZipFile:
        print("Error: Not a valid ZIP file (or file is corrupted).", file=sys.stderr)
        sys.exit(2)

    print(f"Wrote {n} messages to {out_path}")


if __name__ == "__main__":
    main()
