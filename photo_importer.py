#!/usr/bin/env python3
"""Oracle Photo Importer.

Bulk-imports customer photos (.jpg) into the Oracle 19c CUSTOMER_PHOTO table.

Filenames must match the CUSTOMER.CUSTOMERNUMBER value (e.g. ``1234567.jpg``).
The tool looks up CUST_ID via the CUSTOMER table, then MERGEs each photo into
CUSTOMER_PHOTO.PHOTO as a BLOB and stamps PHOTOMODIFIEDDATE = SYSTIMESTAMP.

Usage:
    python photo_importer.py --dir C:\\photos --dsn host:1521/svc --user u --password p

See README.md for full documentation.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import oracledb
except ImportError:
    sys.exit("Missing dependency: pip install oracledb")

try:
    from tqdm import tqdm
except ImportError:
    sys.exit("Missing dependency: pip install tqdm")

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional; env vars can be set externally

LOG = logging.getLogger("photo_importer")

# MERGE so re-runs update an existing row instead of failing with PK violation.
MERGE_SQL = """
MERGE INTO CUSTOMER_PHOTO tgt
USING (SELECT :cust_id AS CUST_ID FROM dual) src
ON (tgt.CUST_ID = src.CUST_ID)
WHEN MATCHED THEN
  UPDATE SET tgt.PHOTO = :photo,
             tgt.PHOTOMODIFIEDDATE = SYSTIMESTAMP
WHEN NOT MATCHED THEN
  INSERT (CUST_ID, PHOTO, PHOTOMODIFIEDDATE)
  VALUES (:cust_id, :photo, SYSTIMESTAMP)
"""


# --------------------------------------------------------------------------- CLI

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="photo_importer",
        description=(
            "Bulk-import customer .jpg photos into Oracle 19c CUSTOMER_PHOTO. "
            "Filenames must be <customernumber>.jpg."
        ),
    )
    p.add_argument("--dir", "-d", required=True,
                   help="Directory containing photo files named <customernumber>.jpg.")
    p.add_argument("--user", "-u", default=os.getenv("ORACLE_USER"),
                   help="Oracle username (or set ORACLE_USER env var).")
    p.add_argument("--password", "-p", default=os.getenv("ORACLE_PASSWORD"),
                   help="Oracle password (or set ORACLE_PASSWORD env var).")
    p.add_argument("--dsn", default=os.getenv("ORACLE_DSN"),
                   help="Oracle DSN as host:port/service (or set ORACLE_DSN env var).")
    p.add_argument("--batch-size", type=int, default=50,
                   help="Rows per executemany batch (default: 50).")
    p.add_argument("--ext", default=".jpg",
                   help="File extension to scan for (default: .jpg).")
    p.add_argument("--dry-run", action="store_true",
                   help="Scan and look up cust_ids but do not write to the DB.")
    p.add_argument("--log-file", default="photo_importer.log",
                   help="Log file path (default: ./photo_importer.log).")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Also log INFO/WARNING messages to the console.")
    args = p.parse_args()

    missing = [k for k in ("user", "password", "dsn") if not getattr(args, k)]
    if missing:
        p.error(
            "Missing required Oracle connection setting(s): "
            + ", ".join(missing)
            + ". Provide via CLI flags or a .env file."
        )
    return args


def setup_logging(log_file: str, verbose: bool) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    handlers: List[logging.Handler] = [logging.FileHandler(log_file, encoding="utf-8")]
    if verbose:
        # tqdm.write() handles stdout safely, but logging straight to stderr is fine.
        handlers.append(logging.StreamHandler(stream=sys.stderr))
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers, force=True)


# --------------------------------------------------------------------------- core

def scan_directory(directory: Path, ext: str) -> List[Path]:
    if not directory.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")
    ext_lc = ext.lower()
    return sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() == ext_lc
    )


def fetch_custid_map(
    conn: "oracledb.Connection", customer_numbers: List[str]
) -> Dict[str, int]:
    """Resolve filename stems -> CUST_ID in batches of 1000.

    Returns a dict keyed by the *normalized* numeric string
    (e.g. "007" and "7" both map to key "7").
    """
    # Normalize and de-duplicate.
    unique_nums: Dict[int, None] = {}
    for raw in customer_numbers:
        try:
            unique_nums[int(raw)] = None
        except ValueError:
            # Filename stem isn't numeric — it can never match. Skip silently.
            continue

    if not unique_nums:
        return {}

    numbers = list(unique_nums.keys())
    mapping: Dict[str, int] = {}
    chunk = 1000  # Oracle's hard IN-list cap.

    cur = conn.cursor()
    cur.arraysize = 1000
    try:
        for i in range(0, len(numbers), chunk):
            slice_ = numbers[i:i + chunk]
            placeholders = ", ".join(f":{j + 1}" for j in range(len(slice_)))
            sql = (
                "SELECT CUSTOMERNUMBER, CUST_ID FROM CUSTOMER "
                f"WHERE CUSTOMERNUMBER IN ({placeholders})"
            )
            cur.execute(sql, slice_)
            for cust_number, cust_id in cur:
                mapping[str(int(cust_number))] = int(cust_id)
    finally:
        cur.close()

    return mapping


def flush_batch(
    cur: "oracledb.Cursor",
    batch: List[Dict[str, object]],
    dry_run: bool,
) -> int:
    """Write a batch via executemany; on failure, retry row-by-row.

    Returns the number of rows successfully written.
    """
    if not batch:
        return 0
    if dry_run:
        return len(batch)

    try:
        cur.executemany(MERGE_SQL, batch)
        return len(batch)
    except oracledb.DatabaseError as exc:
        LOG.warning("Batch failed (%s). Retrying row-by-row to isolate bad rows.", exc)
        success = 0
        for row in batch:
            try:
                cur.execute(MERGE_SQL, row)
                success += 1
            except oracledb.DatabaseError as row_exc:
                LOG.error("Row failed cust_id=%s: %s", row.get("cust_id"), row_exc)
        return success


def import_photos(args: argparse.Namespace) -> Tuple[int, int, int]:
    directory = Path(args.dir).resolve()
    files = scan_directory(directory, args.ext)
    if not files:
        print(f"No '{args.ext}' files found in {directory}")
        return (0, 0, 0)

    print(f"Found {len(files)} file(s) in {directory}")
    print(f"Connecting to Oracle at {args.dsn} as {args.user}...")

    t0 = time.perf_counter()

    with oracledb.connect(user=args.user, password=args.password, dsn=args.dsn) as conn:
        customer_numbers = [f.stem for f in files]
        print("Looking up cust_ids...")
        custid_map = fetch_custid_map(conn, customer_numbers)
        print(f"  Matched {len(custid_map)} of {len(set(customer_numbers))} unique customer numbers.")

        ok = 0
        missing_match = 0
        errors = 0
        batch: List[Dict[str, object]] = []

        cur = conn.cursor()
        # Hint: bind :photo as a real BLOB so files larger than ~32KB work cleanly.
        cur.setinputsizes(photo=oracledb.DB_TYPE_BLOB)

        progress = tqdm(
            files,
            unit="photo",
            dynamic_ncols=True,
            desc="Importing",
            smoothing=0.1,
        )

        try:
            for path in progress:
                try:
                    normalized = str(int(path.stem))
                except ValueError:
                    LOG.warning("Filename is not a numeric customer number: %s", path.name)
                    missing_match += 1
                    progress.set_postfix(ok=ok, missing=missing_match, err=errors)
                    continue

                cust_id = custid_map.get(normalized)
                if cust_id is None:
                    LOG.warning(
                        "No CUSTOMER row for file %s (customernumber=%s)",
                        path.name, normalized,
                    )
                    missing_match += 1
                    progress.set_postfix(ok=ok, missing=missing_match, err=errors)
                    continue

                try:
                    photo_bytes = path.read_bytes()
                except OSError as exc:
                    LOG.error("Failed to read %s: %s", path, exc)
                    errors += 1
                    progress.set_postfix(ok=ok, missing=missing_match, err=errors)
                    continue

                batch.append({"cust_id": cust_id, "photo": photo_bytes})

                if len(batch) >= args.batch_size:
                    written = flush_batch(cur, batch, args.dry_run)
                    ok += written
                    errors += len(batch) - written
                    batch.clear()
                    if not args.dry_run:
                        conn.commit()
                    progress.set_postfix(ok=ok, missing=missing_match, err=errors)

            # Final flush
            if batch:
                written = flush_batch(cur, batch, args.dry_run)
                ok += written
                errors += len(batch) - written
                batch.clear()
                if not args.dry_run:
                    conn.commit()
                progress.set_postfix(ok=ok, missing=missing_match, err=errors)
        finally:
            progress.close()
            cur.close()

    elapsed = time.perf_counter() - t0
    rate = (ok / elapsed) if elapsed > 0 else 0.0
    print(
        f"\nDone in {elapsed:.1f}s ({rate:.1f} photos/s) \u2014 "
        f"{ok} imported, {missing_match} unmatched, {errors} errors."
    )
    if args.dry_run:
        print("(dry-run: no DB writes were performed)")
    return ok, missing_match, errors


# --------------------------------------------------------------------------- entry

def main() -> int:
    args = parse_args()
    setup_logging(args.log_file, args.verbose)
    LOG.info(
        "Starting import: dir=%s dsn=%s user=%s dry_run=%s batch=%d ext=%s",
        args.dir, args.dsn, args.user, args.dry_run, args.batch_size, args.ext,
    )
    try:
        ok, missing, errors = import_photos(args)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 2
    except oracledb.DatabaseError as exc:
        LOG.exception("Database error")
        print(f"Database error: {exc}")
        return 3
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Unexpected error")
        print(f"Error: {exc}")
        return 1

    LOG.info("Finished: ok=%d missing=%d errors=%d", ok, missing, errors)
    return 0 if errors == 0 else 4


if __name__ == "__main__":
    sys.exit(main())
