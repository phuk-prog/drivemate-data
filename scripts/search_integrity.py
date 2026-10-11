"""Stream-validate the complete offline index; format integrity is not address accuracy."""
import argparse
from datetime import date
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

TYPES = set("PCTNRSVHOBAFMEU")
MAX_LINE = 16384


def audit(path):
    path = Path(path)
    report = {"schema": 1, "records_checked": 0, "by_type": {}, "errors": [],
              "scope": "Full file format and ordering; not postal-address completeness or licensing clearance"}
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Search file missing or symlinked")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        report["asset"] = {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
        previous = ""
        with gzip.open(path, "rb") as stream:
            raw = stream.readline(MAX_LINE + 1)
            header = raw.decode("utf-8").rstrip("\n").split("\t")
            if len(raw) > MAX_LINE or len(header) != 4 or header[:2] != ["#drivemate-search-offline", "1"]:
                raise ValueError("Invalid search header/schema")
            date.fromisoformat(header[2])
            if not header[3].strip():
                raise ValueError("Missing source credits")
            report["build_date"] = header[2]
            while True:
                raw = stream.readline(MAX_LINE + 1)
                if not raw:
                    break
                row_number = report["records_checked"] + 2
                if len(raw) > MAX_LINE or not raw.endswith(b"\n"):
                    raise ValueError(f"Oversized or unterminated row {row_number}")
                fields = raw.decode("utf-8").rstrip("\n").split("\t")
                if len(fields) != 6:
                    raise ValueError(f"Expected six fields at row {row_number}")
                key, typ, name, area, lat, lon = fields
                if not re.fullmatch(r"[a-z0-9]+(?: [a-z0-9]+)*", key):
                    raise ValueError(f"Invalid normalised key at row {row_number}")
                if key < previous:
                    raise ValueError(f"Unsorted search key at row {row_number}")
                previous = key
                if typ not in TYPES or (typ != "P" and not name.strip()):
                    raise ValueError(f"Invalid type/name at row {row_number}")
                lat, lon = float(lat), float(lon)
                if not (math.isfinite(lat) and math.isfinite(lon) and 49 <= lat <= 61 and -9 <= lon <= 3):
                    raise ValueError(f"Invalid UK-envelope coordinates at row {row_number}")
                report["records_checked"] += 1
                report["by_type"][typ] = report["by_type"].get(typ, 0) + 1
        if not report["records_checked"]:
            raise ValueError("Search file contains no records")
    except (OSError, EOFError, ValueError, UnicodeError) as exc:
        report["errors"].append(str(exc))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("--out")
    args = parser.parse_args()
    report = audit(args.file)
    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return bool(report["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
