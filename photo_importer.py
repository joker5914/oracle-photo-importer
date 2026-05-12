#!/usr/bin/env python3
"""Customer Photo Importer.

A simple, interactive tool that imports customer photos into an Oracle 19c
database. Walks the operator through every step in plain language; no
command-line flags or config-file editing required.

The Oracle username is fixed (the shared 'envision' account); operators
only need to know its password.
"""
from __future__ import annotations

import getpass
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _die_friendly(message: str) -> None:
    """Show a friendly message, pause, and exit."""
    print()
    print(f"  {message}")
    print()
    try:
        input("  Press Enter to close this window...")
    except (KeyboardInterrupt, EOFError):
        pass
    sys.exit(1)


try:
    import oracledb
except ImportError:
    _die_friendly(
        "The Oracle database library isn't installed yet.\n"
        "  Close this window and run 'Start Photo Importer' again to set things up."
    )

try:
    from tqdm import tqdm
except ImportError:
    _die_friendly(
        "A required component (tqdm) isn't installed yet.\n"
        "  Close this window and run 'Start Photo Importer' again to set things up."
    )


def _get_script_dir() -> Path:
    """Return the directory where settings and logs should live.

    When packaged with PyInstaller's --onefile, ``__file__`` points to a
    temporary extraction directory that disappears at exit, so settings
    would not persist. ``sys.executable`` points to the .exe itself, which
    is where we want settings.json and photo_importer.log to live.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


SCRIPT_DIR = _get_script_dir()
SETTINGS_FILE = SCRIPT_DIR / "settings.json"
LOG_FILE = SCRIPT_DIR / "photo_importer.log"
LOG = logging.getLogger("photo_importer")
BATCH_SIZE = 50

# The Oracle account this tool always logs in as. Everyone who uses the
# tool knows the shared password for this account, so only the password
# needs to be asked for at runtime.
ENVISION_USER = "envision"

# Accepted photo file extensions. .jpg and .jpeg hold the exact same JPEG
# image data, so the tool treats them identically. Case is ignored.
ALLOWED_EXTS = {".jpg", ".jpeg"}

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


# ============================================================================
# UI helpers
# ============================================================================

def banner() -> None:
    print()
    print("  " + "=" * 60)
    print("                  Customer Photo Importer")
    print("  " + "=" * 60)
    print()


def section(title: str) -> None:
    print()
    print(f"  --- {title} ---")
    print()


def info(msg: str = "") -> None:
    if msg:
        print(f"  {msg}")
    else:
        print()


def ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def fail(msg: str) -> None:
    print(f"  [!]   {msg}")


def ask(prompt: str, default: Optional[str] = None, password: bool = False) -> str:
    suffix = f"  [{default}]" if default else ""
    while True:
        if password:
            val = getpass.getpass(f"  {prompt}{suffix}: ")
        else:
            val = input(f"  {prompt}{suffix}: ").strip()
        if not val and default is not None:
            return default
        if val:
            return val
        print("  Please enter a value (or press Ctrl+C to cancel).")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        val = input(f"  {prompt} {suffix}: ").strip().lower()
        if not val:
            return default
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False
        print("  Please type Y for yes or N for no.")


# ============================================================================
# Saved settings
# ============================================================================

def load_settings() -> Dict[str, str]:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Strip any legacy 'user' field; the username is always
                # ENVISION_USER now.
                data.pop("user", None)
                return data
        except Exception as exc:
            LOG.warning("Could not read settings file: %s", exc)
    return {}


def save_settings(settings: Dict[str, str]) -> None:
    # Don't persist the username; it's fixed.
    to_save = {k: v for k, v in settings.items() if k != "user"}
    try:
        SETTINGS_FILE.write_text(json.dumps(to_save, indent=2), encoding="utf-8")
    except OSError as exc:
        LOG.warning("Could not save settings file: %s", exc)


# ============================================================================
# Folder picker (graphical)
# ============================================================================

def pick_folder_dialog(initial: Optional[str] = None) -> Optional[str]:
    """Show a folder-browser dialog. Returns None on cancel or error."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(
            title="Choose the folder that contains your customer photos",
            initialdir=initial if initial and Path(initial).is_dir() else os.getcwd(),
        )
        root.destroy()
        return path or None
    except Exception as exc:
        LOG.warning("Folder picker failed: %s", exc)
        return None


# ============================================================================
# Setup wizard
# ============================================================================

def setup_wizard(saved: Dict[str, str]) -> Dict[str, str]:
    section("Database connection")
    info("Please tell me how to connect to your Oracle database.")
    info("If you don't know any of these, ask your database administrator.")
    print()

    server = ask(
        "Database server name or address (example: db.company.com)",
        default=saved.get("server"),
    )
    port = ask("Database port number", default=saved.get("port") or "1521")
    service = ask(
        "Database service name (example: ORCLPDB1)",
        default=saved.get("service"),
    )
    password = ask(
        f"Password for the '{ENVISION_USER}' database account",
        password=True,
    )

    return {
        "server": server,
        "port": port,
        "service": service,
        "password": password,
    }


# ============================================================================
# Plain-English error explanations
# ============================================================================

def explain_db_error(exc: BaseException) -> None:
    text = str(exc)
    lower = text.lower()

    if "ora-01017" in lower:
        info(f"The database says the password for the '{ENVISION_USER}' account is wrong.")
        info("")
        info("  - Make sure Caps Lock is off.")
        info("  - Type the password carefully (the letters are hidden as you type).")
        info(f"  - If the '{ENVISION_USER}' password was recently changed, use the new one.")
    elif "ora-12514" in lower or "ora-12505" in lower:
        info("The database server answered, but it doesn't recognize the")
        info("service name you entered.")
        info("")
        info("  - Double-check the service name (often something like ORCLPDB1).")
        info("  - Ask your database administrator if you're not sure.")
    elif (
        "dpy-6005" in lower
        or "could not connect" in lower
        or "tns-12541" in lower
        or "12170" in lower
        or "timeout" in lower
    ):
        info("Could not reach the database server. This usually means:")
        info("")
        info("  - The server name or port number is wrong, OR")
        info("  - This computer isn't on the office network / VPN, OR")
        info("  - The database server is currently down.")
        info("")
        info("Check those, then start the tool again.")
    else:
        info("The database returned this message:")
        info(f"  {text}")
        info("")
        info("Try starting the tool again, or contact your IT support.")


# ============================================================================
# File scanning
# ============================================================================

def _stem_key(path: Path) -> str:
    """Normalize a filename stem for matching/dedup.

    Returns the numeric stem as a canonical string ("001234" -> "1234")
    when possible; otherwise the lowercased raw stem.
    """
    try:
        return str(int(path.stem))
    except ValueError:
        return path.stem.lower()


def scan_photo_folder(folder_path: Path) -> Tuple[List[Path], int]:
    """Find photos in the folder and de-duplicate by customer number.

    Accepts both .jpg and .jpeg (case-insensitive). If two files share the
    same customer number (e.g. ``123.jpg`` and ``123.jpeg``, or ``0123.jpg``
    and ``123.jpeg``), the .jpg variant is preferred and the other is
    skipped with a warning written to the log file.

    Returns ``(files_to_import, duplicates_skipped_count)``.
    """
    raw = [
        p for p in folder_path.iterdir()
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTS
    ]

    # Sort so that, for any given customer number, .jpg is encountered
    # before .jpeg. Then within an extension, sort by name for stable order.
    def sort_key(p: Path):
        ext_priority = 0 if p.suffix.lower() == ".jpg" else 1
        return (_stem_key(p), ext_priority, p.name.lower())

    raw.sort(key=sort_key)

    seen: Dict[str, Path] = {}
    deduped: List[Path] = []
    duplicates = 0
    for p in raw:
        key = _stem_key(p)
        if key in seen:
            LOG.warning(
                "Multiple files for the same customer number: "
                "keeping '%s', skipping '%s'",
                seen[key].name, p.name,
            )
            duplicates += 1
            continue
        seen[key] = p
        deduped.append(p)

    return deduped, duplicates


# ============================================================================
# Database core
# ============================================================================

def fetch_custid_map(
    conn: "oracledb.Connection", customer_numbers: List[str]
) -> Dict[str, int]:
    """Resolve filename stems to CUST_IDs via a single batched query."""
    unique_nums: Dict[int, None] = {}
    for raw in customer_numbers:
        try:
            unique_nums[int(raw)] = None
        except ValueError:
            continue
    if not unique_nums:
        return {}
    numbers = list(unique_nums)
    mapping: Dict[str, int] = {}
    cur = conn.cursor()
    cur.arraysize = 1000
    try:
        chunk = 1000  # Oracle's IN-list hard limit
        for i in range(0, len(numbers), chunk):
            slice_ = numbers[i : i + chunk]
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


def flush_batch(cur: "oracledb.Cursor", batch: List[Dict[str, object]]) -> int:
    """Write a batch with executemany; on failure, fall back to row-by-row."""
    if not batch:
        return 0
    try:
        cur.executemany(MERGE_SQL, batch)
        return len(batch)
    except oracledb.DatabaseError as exc:
        LOG.warning("Batch failed (%s). Retrying photos one at a time.", exc)
        success = 0
        for row in batch:
            try:
                cur.execute(MERGE_SQL, row)
                success += 1
            except oracledb.DatabaseError as row_exc:
                LOG.error("Photo failed cust_id=%s: %s", row.get("cust_id"), row_exc)
        return success


def import_photos(
    conn: "oracledb.Connection", files: List[Path]
) -> Tuple[int, int, int]:
    customer_numbers = [f.stem for f in files]
    info("Looking up customer records in the database...")
    custid_map = fetch_custid_map(conn, customer_numbers)
    info(f"Matched {len(custid_map)} customer number(s) in the database.")
    if not custid_map:
        print()
        fail("None of the photo file names match any customer numbers.")
        info("File names need to match the customer number, like '1234567.jpg'.")
        return 0, len(files), 0

    print()
    ok_count = 0
    missing = 0
    errors = 0
    batch: List[Dict[str, object]] = []

    cur = conn.cursor()
    cur.setinputsizes(photo=oracledb.DB_TYPE_BLOB)

    progress = tqdm(
        files,
        unit="photo",
        dynamic_ncols=True,
        desc="  Importing",
        smoothing=0.1,
    )

    try:
        for path in progress:
            try:
                normalized = str(int(path.stem))
            except ValueError:
                LOG.warning("File name is not a number: %s", path.name)
                missing += 1
                progress.set_postfix(done=ok_count, skipped=missing, errors=errors)
                continue
            cust_id = custid_map.get(normalized)
            if cust_id is None:
                LOG.warning("No customer found for: %s", path.name)
                missing += 1
                progress.set_postfix(done=ok_count, skipped=missing, errors=errors)
                continue
            try:
                blob = path.read_bytes()
            except OSError as exc:
                LOG.error("Could not read %s: %s", path, exc)
                errors += 1
                progress.set_postfix(done=ok_count, skipped=missing, errors=errors)
                continue
            batch.append({"cust_id": cust_id, "photo": blob})
            if len(batch) >= BATCH_SIZE:
                written = flush_batch(cur, batch)
                ok_count += written
                errors += len(batch) - written
                batch.clear()
                conn.commit()
                progress.set_postfix(done=ok_count, skipped=missing, errors=errors)
        if batch:
            written = flush_batch(cur, batch)
            ok_count += written
            errors += len(batch) - written
            batch.clear()
            conn.commit()
            progress.set_postfix(done=ok_count, skipped=missing, errors=errors)
    finally:
        progress.close()
        cur.close()

    return ok_count, missing, errors


# ============================================================================
# Main flow
# ============================================================================

def _run_app() -> int:
    banner()
    info("Welcome! This tool copies customer photos into the database.")
    info("Just answer the questions and we'll do the rest.")
    print()

    saved = load_settings()

    # ---- Step 1: connection settings ----
    if saved.get("server") and saved.get("password"):
        info(f"Last time you connected to '{saved['server']}'.")
        if ask_yes_no("Use the same database settings as last time?", default=True):
            settings = dict(saved)
        else:
            settings = setup_wizard(saved)
    else:
        section("First-time setup")
        settings = setup_wizard(saved)

    dsn = f"{settings['server']}:{settings['port']}/{settings['service']}"

    # ---- Step 2: test the connection ----
    section("Connecting to the database")
    info(f"Connecting to {settings['server']} as '{ENVISION_USER}' ...")
    try:
        conn = oracledb.connect(
            user=ENVISION_USER,
            password=settings["password"],
            dsn=dsn,
        )
    except oracledb.DatabaseError as exc:
        LOG.exception("Connection failed")
        print()
        fail("Could not connect to the database.")
        print()
        explain_db_error(exc)
        return 1

    ok("Connected!")
    save_settings(settings)  # only after a successful connect

    try:
        # ---- Step 3: pick the photo folder ----
        section("Choose your photo folder")
        info("A window will pop up so you can browse to your folder.")
        info("(If the window doesn't appear, look behind this one.)")
        folder = pick_folder_dialog(initial=saved.get("last_folder"))
        if not folder:
            print()
            info("No folder was picked.")
            folder = ask(
                "Type the full path to your photo folder",
                default=saved.get("last_folder"),
            )
        folder_path = Path(folder).expanduser().resolve()
        if not folder_path.is_dir():
            print()
            fail(f"That folder doesn't exist: {folder_path}")
            info("Double-check the path and try again.")
            return 1
        settings["last_folder"] = str(folder_path)
        save_settings(settings)

        # ---- Step 4: scan ----
        files, duplicates = scan_photo_folder(folder_path)
        if not files:
            print()
            fail(f"No .jpg or .jpeg photos were found in {folder_path}")
            info("Make sure the folder contains photos ending in .jpg or .jpeg")
            return 1

        print()
        info(f"Found {len(files)} photo(s) in:")
        info(f"  {folder_path}")
        if duplicates:
            info(
                f"({duplicates} extra file(s) shared a customer number with another "
                "and will be skipped.)"
            )
        print()
        if not ask_yes_no(f"Ready to import these {len(files)} photo(s)?", default=True):
            print()
            info("OK, cancelled. No changes were made.")
            return 0

        # ---- Step 5: import ----
        section("Importing photos")
        t0 = time.perf_counter()
        ok_count, missing, errors = import_photos(conn, files)
        elapsed = time.perf_counter() - t0

        # ---- Step 6: summary ----
        print()
        print("  " + "=" * 60)
        print("                          All Done!")
        print("  " + "=" * 60)
        print()
        print(f"     Imported successfully:        {ok_count}")
        print(f"     No matching customer:         {missing}")
        print(f"     Could not read file:          {errors}")
        if duplicates:
            print(f"     Duplicate files skipped:      {duplicates}")
        print(f"     Time taken:                   {elapsed:.1f} seconds")
        print()
        if missing or errors or duplicates:
            info("Some photos were skipped. Details are in:")
            info(f"  {LOG_FILE.name}")
            print()

        return 0 if errors == 0 else 4
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(str(LOG_FILE), encoding="utf-8")],
        force=True,
    )
    try:
        return _run_app()
    except KeyboardInterrupt:
        print()
        info("Cancelled. No more changes will be made.")
        return 130
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Unexpected error")
        print()
        fail(f"Something went wrong: {exc}")
        info(f"Details have been saved to: {LOG_FILE.name}")
        return 1
    finally:
        try:
            print()
            input("  Press Enter to close this window...")
        except (KeyboardInterrupt, EOFError):
            pass


if __name__ == "__main__":
    sys.exit(main())
