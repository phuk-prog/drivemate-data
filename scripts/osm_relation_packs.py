"""Preserve OPL relation facts in deterministic gzip NDJSON, without interpreting lanes.

Input may contain the entire OPL stream; node and way records are skipped. Relation
IDs, decoded tags and ordered typed members are retained. A disk-backed SQLite
spool bounds memory and rejects duplicate IDs before a new output directory appears.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

BUCKET_SIZE = 100_000
MAX_LINE_BYTES = 16 * 1024 * 1024
ESCAPE = re.compile(r"%([0-9a-fA-F]+)%")
MEMBER = re.compile(r"([nwr])([1-9][0-9]*)@(.*)\Z")
TYPES = {"n": "node", "w": "way", "r": "relation"}
ATTRIBUTION = "© OpenStreetMap contributors; ODbL-1.0"
PACK_NAME = re.compile(r"relation-packs-(0|[1-9][0-9]*)\.jsonl\.gz\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def unique_json(text):
    def object_pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("Duplicate JSON object key")
            obj[key] = value
        return obj
    return json.loads(text, object_pairs_hook=object_pairs)


def validate_record(record):
    if not isinstance(record, dict) or set(record) != {"id", "tags", "members"}:
        raise ValueError("Invalid relation record schema")
    if type(record["id"]) is not int:
        raise ValueError("Invalid relation ID type")
    checked_id(record["id"])
    if not isinstance(record["tags"], dict) or any(
            not isinstance(k, str) or not k or not isinstance(v, str) for k, v in record["tags"].items()):
        raise ValueError("Invalid relation tags")
    if not isinstance(record["members"], list):
        raise ValueError("Invalid relation member list")
    for member in record["members"]:
        if (not isinstance(member, dict) or set(member) != {"type", "ref", "role"}
                or member["type"] not in TYPES.values() or type(member["ref"]) is not int
                or not isinstance(member["role"], str)):
            raise ValueError("Invalid typed relation member")
        checked_id(member["ref"])
    return record


def validate_directory(directory):
    """Rehash every compressed file and independently validate its decompressed records."""
    root = Path(directory)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Relation directory missing or unsafe")
    manifest_path = root / "relation-packs-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink() or manifest_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Relation manifest missing or unsafe")
    manifest = unique_json(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Invalid relation manifest object")
    if (type(manifest.get("schema")) is not int or manifest["schema"] != 1
            or manifest.get("attribution") != ATTRIBUTION
            or manifest.get("bucket_size") != BUCKET_SIZE
            or type(manifest.get("relations")) is not int or manifest["relations"] < 0
            or not isinstance(manifest.get("source_opl_sha256"), str)
            or not SHA.fullmatch(manifest["source_opl_sha256"])
            or not isinstance(manifest.get("files"), list)):
        raise ValueError("Invalid relation manifest")
    names, last_bucket, total = set(), -1, 0
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != {"name", "bytes", "sha256", "records"}:
            raise ValueError("Invalid relation pack metadata")
        name = entry["name"]
        match = PACK_NAME.fullmatch(name) if isinstance(name, str) else None
        if match is None or name in names or int(match[1]) <= last_bucket:
            raise ValueError("Invalid, duplicate or unordered relation bucket")
        bucket = last_bucket = int(match[1])
        names.add(name)
        pack = root / name
        if (not pack.is_file() or pack.is_symlink() or type(entry["bytes"]) is not int
                or entry["bytes"] <= 0 or pack.stat().st_size != entry["bytes"]
                or not isinstance(entry["sha256"], str) or not SHA.fullmatch(entry["sha256"])
                or file_digest(pack) != entry["sha256"]
                or type(entry["records"]) is not int or entry["records"] <= 0):
            raise ValueError("Relation pack integrity metadata mismatch")
        before = pack.stat()
        records, last_id = 0, -1
        with gzip.open(pack, "rb") as stream:
            while True:
                line = stream.readline(MAX_LINE_BYTES * 6 + 1)
                if not line:
                    break
                if len(line) > MAX_LINE_BYTES * 6 or not line.endswith(b"\n"):
                    raise ValueError("Unbounded or incomplete relation JSON record")
                record = validate_record(unique_json(line))
                ident = record["id"]
                if ident <= last_id or ident // BUCKET_SIZE != bucket:
                    raise ValueError("Relation ID is duplicate, unordered or in wrong bucket")
                last_id = ident
                records += 1
        after = pack.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("Relation pack changed during verification")
        if records != entry["records"]:
            raise ValueError("Relation record count mismatch")
        total += records
    if total != manifest["relations"] or {p.name for p in root.iterdir()} != names | {manifest_path.name}:
        raise ValueError("Relation total or directory inventory mismatch")
    return manifest


def unescape(raw):
    # OPL escaping represents Unicode code points, matching junction_topology.
    cursor, pieces = 0, []
    for match in ESCAPE.finditer(raw):
        plain = raw[cursor:match.start()]
        if "%" in plain:
            raise ValueError("Malformed OPL percent escape")
        pieces.append(plain)
        codepoint = int(match[1], 16)
        if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError("Invalid OPL Unicode code point")
        pieces.append(chr(codepoint))
        cursor = match.end()
    suffix = raw[cursor:]
    if "%" in suffix:
        raise ValueError("Malformed OPL percent escape")
    return "".join(pieces) + suffix


def checked_id(value):
    ident = int(value)
    if not 0 < ident <= 2**63 - 1:
        raise ValueError("OSM identifier outside supported positive range")
    return ident


def parse_relation(line):
    fields = line.strip().split()
    if not fields or fields[0].startswith(("n", "w")):
        return None
    if not re.fullmatch(r"r[1-9][0-9]*", fields[0]):
        raise ValueError("Malformed or unexpected OPL object record")
    ident = checked_id(fields[0][1:])
    tags_fields = [field[1:] for field in fields[1:] if field.startswith("T")]
    member_fields = [field[1:] for field in fields[1:] if field.startswith("M")]
    if len(tags_fields) != 1 or len(member_fields) != 1:
        raise ValueError(f"Relation {ident}: missing or duplicate tag/member field")
    tags = {}
    if tags_fields[0]:
        for pair in tags_fields[0].split(","):
            if "=" not in pair:
                raise ValueError(f"Relation {ident}: malformed tag")
            key, value = pair.split("=", 1)
            key, value = unescape(key), unescape(value)
            if not key or key in tags:
                raise ValueError(f"Relation {ident}: empty or duplicate tag key")
            tags[key] = value
    members = []
    if member_fields[0]:
        for member in member_fields[0].split(","):
            match = MEMBER.fullmatch(member)
            if match is None:
                raise ValueError(f"Relation {ident}: malformed typed member")
            members.append({"type": TYPES[match[1]], "ref": checked_id(match[2]), "role": unescape(match[3])})
    return {"id": ident, "tags": tags, "members": members}


def build_packs(input_path, output_dir):
    """Create a new directory atomically; failures never expose a partial dataset."""
    source, output = Path(input_path), Path(output_dir)
    if not source.is_file() or source.is_symlink():
        raise ValueError("Input OPL missing or unsafe")
    if output.exists() or output.is_symlink():
        raise ValueError("Output directory must be new")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".relation-packs-", dir=output.parent))
    database = None
    try:
        database = sqlite3.connect(temporary / "spool.sqlite")
        database.execute("PRAGMA cache_size=-2048")
        database.execute("PRAGMA temp_store=FILE")
        database.execute("CREATE TABLE relations (id INTEGER PRIMARY KEY, record TEXT NOT NULL)")
        count = 0
        source_hash = hashlib.sha256()
        source_stat = source.stat()
        with source.open("rb") as stream:
            while True:
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                source_hash.update(raw)
                if len(raw) > MAX_LINE_BYTES:
                    raise ValueError("OPL record exceeds bounded parser limit")
                record = parse_relation(raw.decode("utf-8"))
                if record is None:
                    continue
                try:
                    database.execute("INSERT INTO relations VALUES (?, ?)",
                                     (record["id"], json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
                except sqlite3.IntegrityError as error:
                    raise ValueError("Duplicate OSM relation ID") from error
                count += 1
                if count % 1000 == 0:
                    database.commit()
        source_after = source.stat()
        if (source_stat.st_size, source_stat.st_mtime_ns, source_stat.st_ino) != (
                source_after.st_size, source_after.st_mtime_ns, source_after.st_ino):
            raise ValueError("OPL source changed during relation extraction")
        database.commit()
        filenames, bucket_counts, current_bucket = [], {}, None
        compressed, target = None, None
        try:
            for ident, text in database.execute("SELECT id, record FROM relations ORDER BY id"):
                bucket = ident // BUCKET_SIZE
                if bucket != current_bucket:
                    if compressed is not None:
                        compressed.close()
                        target.close()
                    filename = f"relation-packs-{bucket}.jsonl.gz"
                    filenames.append(filename)
                    target = (temporary / filename).open("wb")
                    compressed = gzip.GzipFile(filename="", fileobj=target, mode="wb", compresslevel=9, mtime=0)
                    current_bucket = bucket
                compressed.write((text + "\n").encode("utf-8"))
                bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        finally:
            if compressed is not None:
                compressed.close()
            if target is not None:
                target.close()
        database.close()
        database = None
        (temporary / "spool.sqlite").unlink()
        manifest = {"schema": 1, "attribution": ATTRIBUTION, "source_opl_sha256": source_hash.hexdigest(),
                    "relations": count, "bucket_size": BUCKET_SIZE,
                    "files": [{"name": name, "bytes": (temporary / name).stat().st_size,
                               "sha256": file_digest(temporary / name),
                               "records": bucket_counts[int(PACK_NAME.fullmatch(name)[1])]}
                              for name in filenames],
                    "scope": "OSM relation tags and ordered references; no inferred lane paths"}
        (temporary / "relation-packs-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        validate_directory(temporary)
        if output.exists() or output.is_symlink():
            raise ValueError("Output appeared during build; refusing replacement")
        temporary.rename(output)
        return manifest
    finally:
        if database is not None:
            database.close()
        if temporary.exists():
            shutil.rmtree(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build_packs(args.input, args.output), sort_keys=True))
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"OSM relation packs: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
