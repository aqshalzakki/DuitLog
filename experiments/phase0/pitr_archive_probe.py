"""Encrypted multi-binlog recovery drill for disposable Windows MySQL fixtures."""
import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
import uuid

import cryptography
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import mysql_probe
from mysql_probe import DB, Instance, check, deduct, run


BINLOG = re.compile(r"probe-bin\.(\d{6})")
MANIFEST = "manifest"
DUMP = "backup.sql"


@dataclass(frozen=True)
class Archive:
    name: str
    write: Callable[[str, bytes], None]
    read: Callable[[str], bytes]


def directory_archive(parent, name):
    directory = parent.resolve(strict=True) / name
    directory.mkdir()

    def write(filename, data):
        with (directory / filename).open("xb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())

    return Archive(name, write, lambda filename: (directory / filename).read_bytes())


def s3_archive(client, bucket, prefix, name):
    directory = f"{prefix.strip('/')}/{name}"

    def write(filename, data):
        client.put_object(Bucket=bucket, Key=f"{directory}/{filename}", Body=data,
                          ContentType="application/octet-stream", IfNoneMatch="*")

    def read(filename):
        with client.get_object(Bucket=bucket, Key=f"{directory}/{filename}")["Body"] as body:
            return body.read()

    return Archive(name, write, read)


def connect_s3(endpoint, region, profile):
    import boto3
    from botocore.config import Config

    return boto3.Session(profile_name=profile).client(
        "s3", endpoint_url=endpoint, region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                      request_checksum_calculation="when_required",
                      response_checksum_validation="when_required",
                      connect_timeout=5, read_timeout=15,
                      retries={"mode": "standard", "total_max_attempts": 3}),
    )


def coordinates(source):
    filename, position, *_ = source.rows("SHOW MASTER STATUS")[0].split("\t")
    if BINLOG.fullmatch(filename) is None:
        raise ValueError("unexpected binlog basename")
    return filename, int(position)


def catalog(archive, key, filename, plaintext=None, *, read=None):
    object_name = filename + ".aead"
    aad = f"duit-pitr-v1/{archive.name}/{filename}".encode()
    if plaintext is None:
        data = (read or archive.read)(object_name)
        return key.decrypt(data[:12], data[12:], aad)
    nonce = os.urandom(12)
    archive.write(object_name, nonce + key.encrypt(nonce, plaintext, aad))
    return None


def read_archive(archive, key, *, read=None):
    manifest = json.loads(catalog(archive, key, MANIFEST, read=read))
    segments = manifest["segments"]
    matches = [BINLOG.fullmatch(segment["filename"]) for segment in segments]
    if not matches or any(match is None for match in matches):
        raise ValueError("invalid binlog names")
    sequence = [int(match[1]) for match in matches]
    if sequence != list(range(sequence[0], sequence[0] + len(sequence))):
        raise ValueError("binlog sequence has a gap")
    start, stop = manifest["start"], manifest["stop"]
    if start < 4 or stop < 4 or (len(segments) == 1 and stop < start):
        raise ValueError("invalid recovery positions")
    dump = catalog(archive, key, DUMP, read=read)
    dump_checkpoint = re.search(
        rb"(?:SOURCE|MASTER)_LOG_FILE\s*=\s*'([^']+)',\s*(?:SOURCE|MASTER)_LOG_POS\s*=\s*(\d+)",
        dump,
    )
    if dump_checkpoint is None or dump_checkpoint.groups() != (
        segments[0]["filename"].encode(), str(start).encode()
    ):
        raise ValueError("backup checkpoint and archive manifest disagree")
    logs = [catalog(archive, key, segment["filename"], read=read) for segment in segments]
    if start > len(logs[0]) or stop > len(logs[-1]):
        raise ValueError("recovery positions exceed archived binlogs")
    return manifest, dump, logs


def expect_failure(error_type, operation):
    try:
        operation()
    except error_type:
        return
    raise AssertionError(f"expected {error_type.__name__}")


def verify_archive_rejections(archive, key, segments):
    first = segments[0]["filename"] + ".aead"
    second = segments[1]["filename"] + ".aead"

    # Inject failures against a read-only copy so tests never modify the archived objects.
    names = (MANIFEST + ".aead", DUMP + ".aead", first, second)
    stored = {name: archive.read(name) for name in names}

    def missing(name):
        if name == first:
            raise FileNotFoundError(name)
        return stored[name]

    def tampered(name):
        contents = stored[name]
        if name == first:
            return contents[:-1] + bytes([contents[-1] ^ 1])
        return contents

    def swapped(name):
        return stored[second if name == first else name]

    expect_failure(FileNotFoundError, lambda: read_archive(archive, key, read=missing))
    expect_failure(InvalidTag, lambda: read_archive(archive, key, read=tampered))
    expect_failure(InvalidTag, lambda: read_archive(archive, key, read=swapped))
    wrong_key = AESGCM(AESGCM.generate_key(bit_length=256))
    expect_failure(InvalidTag, lambda: read_archive(archive, wrong_key, read=stored.__getitem__))
    print("Missing, corrupted and swapped binlogs and a wrong key all blocked restore", flush=True)


def seed(source):
    source.query(f"""CREATE DATABASE {DB}; USE {DB};
        CREATE TABLE account (id INT PRIMARY KEY, balance BIGINT, next_seq BIGINT) ENGINE=InnoDB;
        CREATE TABLE activity (owner INT, effective_at DATETIME(6), seq BIGINT, delta BIGINT,
            target BIGINT, PRIMARY KEY (owner,effective_at,seq), UNIQUE KEY(owner,seq)) ENGINE=InnoDB;
        CREATE TABLE audit (owner INT, seq BIGINT, PRIMARY KEY(owner,seq)) ENGINE=InnoDB;
        CREATE TABLE outcome (owner INT, attempt VARCHAR(30), seq BIGINT,
            PRIMARY KEY(owner,attempt)) ENGINE=InnoDB;
        CREATE TABLE receivable (owner INT, borrower INT, balance BIGINT,
            PRIMARY KEY(owner,borrower)) ENGINE=InnoDB;
        CREATE TABLE receivable_event (owner INT, borrower INT, seq BIGINT, delta BIGINT,
            PRIMARY KEY(owner,borrower,seq)) ENGINE=InnoDB;
        INSERT INTO account VALUES (1,70,3);
        INSERT INTO activity VALUES
            (1,'2026-01-01 08:00:00',1,100,100),
            (1,'2026-01-01 10:00:00',2,-30,70);
        INSERT INTO audit VALUES (1,1),(1,2);
        INSERT INTO outcome VALUES (1,'snapshot-a',1),(1,'snapshot-b',2);
        INSERT INTO receivable VALUES (1,1,20);
        INSERT INTO receivable_event VALUES (1,1,1,25),(1,1,2,-5);""")


def verify_restore(restored):
    query = lambda sql: restored.rows(f"USE {DB}; {sql}")
    balance = 0
    snapshots = []
    for row in query("SELECT seq,delta,target FROM activity WHERE owner=1 ORDER BY effective_at,seq"):
        seq, delta, target = row.split("\t")
        balance += int(delta)
        if target != "NULL":
            check(balance, int(target))
            snapshots.append((int(seq), balance))
    check(snapshots, [(1, 100), (2, 70)])
    check(balance, 62)
    check(query("SELECT balance,next_seq FROM account WHERE id=1"), ["62\t5"])
    outstanding = 0
    for delta in query("SELECT delta FROM receivable_event WHERE owner=1 AND borrower=1 ORDER BY seq"):
        outstanding += int(delta)
        if outstanding < 0:
            raise AssertionError("negative receivable prefix")
    check(query("SELECT balance FROM receivable WHERE owner=1 AND borrower=1"), [str(outstanding)])
    check(outstanding, 20)
    check(query("""SELECT a.seq,o.attempt FROM activity a
        JOIN audit u ON u.owner=a.owner AND u.seq=a.seq
        JOIN outcome o ON o.owner=a.owner AND o.seq=a.seq
        ORDER BY a.seq"""), ["1\tsnapshot-a", "2\tsnapshot-b", "3\tarchived-a", "4\tarchived-b"])
    check(query("SELECT COUNT(*) FROM audit; SELECT COUNT(*) FROM outcome;"), ["4", "4"])
    check(query("SELECT COUNT(*) FROM outcome WHERE attempt='acknowledged-missing'"), ["0"])
    check(restored.rows("SELECT @@skip_networking, @@port"), ["1\t0"])


def close_and_archive(source, archive, key, name):
    source.query("FLUSH BINARY LOGS")
    check(coordinates(source)[0] != name, True)
    catalog(archive, key, name, (source.folder / name).read_bytes())
    return {"filename": name, "archivedAt": datetime.now(UTC).isoformat()}


def capture(source_dir, archive, key):
    with Instance(source_dir / "data", 111).start() as source:
        seed(source)
        filename, start = coordinates(source)
        dump = source.client("mysqldump", "--single-transaction", "--source-data=2",
                             "--set-gtid-purged=OFF", "--databases", DB).stdout
        catalog(archive, key, DUMP, dump)
        source.query(deduct(5, "archived-a"))
        first = close_and_archive(source, archive, key, filename)

        source.query(deduct(3, "archived-b"))
        recovered_through = datetime.now(UTC)
        filename, stop = coordinates(source)
        second = close_and_archive(source, archive, key, filename)
        segments = [first, second]
        catalog(archive, key, MANIFEST, json.dumps({
            "start": start, "stop": stop, "segments": segments,
            "recoveredThrough": recovered_through.isoformat(),
        }).encode())
        archive_ready = datetime.now(UTC)
        source.query(deduct(7, "acknowledged-missing"))
        check(source.rows(f"USE {DB}; SELECT balance,next_seq FROM account WHERE id=1"), ["55\t6"])
        return segments, recovered_through, archive_ready, datetime.now(UTC), time.monotonic()


def main(workspace, archive):
    key = AESGCM(AESGCM.generate_key(bit_length=256))
    with tempfile.TemporaryDirectory(prefix="source-", dir=workspace) as folder:
        source_dir = Path(folder).resolve(strict=True)
        check(source_dir.parent, workspace.resolve(strict=True))
        segments, recovered_through, archive_ready, incident, started = capture(source_dir, archive, key)
    check(source_dir.exists(), False)
    verify_archive_rejections(archive, key, segments)
    manifest, dump, logs = read_archive(archive, key)
    paths = []
    for segment, data in zip(manifest["segments"], logs, strict=True):
        path = workspace / segment["filename"]
        path.write_bytes(data)
        paths.append(str(path))
    replay = run("mysqlbinlog", f"--start-position={manifest['start']}",
                 f"--stop-position={manifest['stop']}", "--verify-binlog-checksum", *paths).stdout
    with Instance(workspace / "restore", 112).start() as restored:
        restored.client("mysql", "--binary-mode", data=dump)
        restored.client("mysql", "--binary-mode", data=replay)
        verify_restore(restored)
        print("Restore verified: balance 62, two snapshots, receivable 20, four audit/outcome pairs")
        print("Acknowledged unarchived debit remains missing; isolated restore TCP is disabled")
        print(f"Commit-to-archive wait {(archive_ready - recovered_through).total_seconds():.2f}s; "
              f"synthetic recovery gap {(incident - recovered_through).total_seconds():.2f}s; "
              f"incident-to-verification {time.monotonic() - started:.2f}s", flush=True)
        print(f"Recovered through {manifest['recoveredThrough']}; "
              f"{segments[0]['filename']}:{manifest['start']} to "
              f"{segments[-1]['filename']}:{manifest['stop']}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, help="existing directory on a test mount")
    parser.add_argument("--s3-endpoint")
    parser.add_argument("--s3-bucket")
    parser.add_argument("--s3-prefix")
    parser.add_argument("--s3-profile")
    parser.add_argument("--s3-region")
    args = parser.parse_args()
    s3_fields = (args.s3_endpoint, args.s3_bucket, args.s3_prefix,
                 args.s3_profile, args.s3_region)
    if any(s3_fields):
        if not all(s3_fields) or args.archive_dir:
            parser.error("S3 mode requires all five --s3 options and excludes --archive-dir")
        endpoint = urlsplit(args.s3_endpoint)
        if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username is not None
                or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment):
            parser.error("S3 endpoint must be an HTTPS origin")
        if not args.s3_prefix.strip("/").strip():
            parser.error("S3 prefix must be non-empty")
    try:
        with tempfile.TemporaryDirectory(prefix="duit-pitr-", dir=Path.cwd()) as folder:
            workspace = Path(folder)
            mysql_probe.WORK = workspace
            name = "duit-drill-" + uuid.uuid4().hex
            print(f"Archive {name}; cryptography {cryptography.__version__}", flush=True)
            if args.s3_endpoint:
                client = connect_s3(args.s3_endpoint, args.s3_region, args.s3_profile)
                try:
                    main(workspace, s3_archive(client, args.s3_bucket, args.s3_prefix, name))
                finally:
                    client.close()
            else:
                main(workspace, directory_archive(args.archive_dir or workspace, name))
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.stderr.decode(errors="replace") or str(error)) from error
