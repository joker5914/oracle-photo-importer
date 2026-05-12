#!/usr/bin/env python3
"""Customer Photo Importer.

A simple, interactive tool that imports customer photos into an Oracle 19c
database. Walks the operator through every step in plain language; no
command-line flags or config-file editing required for interactive use.

Also supports an --unattended mode for automated runs from Windows Task
Scheduler or any other scheduler. See parse_args() and the README for
details.

The Oracle username is fixed (the shared 'envision' account); operators
only need to know its password. The database server, port, and service
name are auto-detected from any tnsnames.ora file found on the local
machine. The Envision password is stored in Windows Credential Manager
(per-user), not in any file on disk.
"""
from __future__ import annotations

import sys

# ============================================================================
# Detect --unattended early (before heavy imports) so we can skip the
# interactive loading banner when running from Task Scheduler. The full
# argparse-based parse happens later via parse_args(); this is just a quick
# check of argv so the banner decision can be made immediately.
# ============================================================================
_UNATTENDED_EARLY = (
    "--unattended" in sys.argv
    or "--auto" in sys.argv
    or "-y" in sys.argv
)

if not _UNATTENDED_EARLY:
    print()
    print("  ============================================================")
    print("                  Customer Photo Importer")
    print("  ============================================================")
    print()
    print("  Starting up, please wait a moment...")
    print()
    print("  The first launch can take a few seconds while the program")
    print("  unpacks itself. Please don't close this window - it isn't")
    print("  frozen, just loading.")
    print()
    sys.stdout.flush()

# Lightweight standard-library imports next.
import argparse
import getpass
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _die_friendly(message: str) -> None:
    """Show a friendly message, pause, and exit."""
    print()
    print(f"  {message}")
    print()
    if not _UNATTENDED_EARLY:
        try:
            input("  Press Enter to close this window...")
        except (KeyboardInterrupt, EOFError):
            pass
    sys.exit(1)


# Heavy third-party imports last - these take a noticeable moment to load
# in a packaged .exe, so the message above is already on screen by now.
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

try:
    import keyring
    from keyring.errors import KeyringError
except ImportError:
    _die_friendly(
        "A required component (keyring) isn't installed yet.\n"
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

# Exit codes used by the tool. Documented in the README so Task Scheduler
# can branch on them.
EXIT_OK = 0
EXIT_GENERIC_ERROR = 1
EXIT_BAD_CONFIG = 2       # missing settings / bad folder path
EXIT_DB_ERROR = 3         # connect / auth failed
EXIT_PARTIAL_IMPORT = 4   # ran, but some photos failed
EXIT_INTERRUPTED = 130    # Ctrl+C / cancel

# The Oracle account this tool always logs in as. Everyone who uses the
# tool knows the shared password for this account, so only the password
# needs to be asked for at runtime.
ENVISION_USER = "envision"

# Name shown for this tool's entry in Windows Credential Manager.
# Visible under Control Panel > Credential Manager > Windows Credentials.
KEYRING_SERVICE = "Customer Photo Importer"

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
# Argument parsing
# ============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Interactive use needs no arguments at all. Automation (Task Scheduler,
    cron-style runners, CI jobs) should pass --unattended so the tool runs
    end-to-end with no prompts and a non-zero exit code on any failure.
    """
    parser = argparse.ArgumentParser(
        prog="Customer.Photo.Importer",
        description=(
            "Imports customer photos into the Oracle database. Runs "
            "interactively by default; pass --unattended to run from "
            "Windows Task Scheduler or any other automation."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  Customer.Photo.Importer.exe\n"
            "      Interactive mode. Walks you through each step.\n\n"
            "  Customer.Photo.Importer.exe --unattended\n"
            "      No prompts. Uses the database settings and folder saved\n"
            "      from a previous interactive run.\n\n"
            "  Customer.Photo.Importer.exe --unattended --folder \"C:\\photos\\inbox\"\n"
            "      No prompts. Imports from a specific folder.\n\n"
            "exit codes:\n"
            "  0   Success\n"
            "  1   Unexpected error (see photo_importer.log)\n"
            "  2   Missing settings or invalid --folder path\n"
            "  3   Database connection or authentication failed\n"
            "  4   Import completed but some photos failed\n"
            "  130 Cancelled by user\n"
        ),
    )
    parser.add_argument(
        "--unattended", "--auto", "-y",
        action="store_true",
        dest="unattended",
        help=(
            "Run with no prompts. Requires saved settings (server, port, "
            "service) and the Envision password in Windows Credential Manager "
            "for the user account running the tool. Fails fast with a non-zero "
            "exit code on any error."
        ),
    )
    parser.add_argument(
        "--folder", "-f",
        dest="folder",
        metavar="PATH",
        help=(
            "Photo folder to import from. Defaults to the last folder used. "
            "Required for unattended mode if no folder has ever been saved."
        ),
    )
    return parser.parse_args()


# ============================================================================
# UI helpers
# ============================================================================

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


def ask_choice(prompt: str, max_choice: int, default: int = 1) -> int:
    """Ask the user to pick a number between 1 and ``max_choice``."""
    while True:
        val = input(f"  {prompt}  [{default}]: ").strip()
        if not val:
            return default
        try:
            n = int(val)
            if 1 <= n <= max_choice:
                return n
        except ValueError:
            pass
        print(f"  Please enter a number between 1 and {max_choice}.")


# ============================================================================
# Saved settings
#
# Non-secret settings (server, port, service, last_folder) live in
# settings.json next to the .exe.
#
# The Envision password lives in Windows Credential Manager under the
# service name 'Customer Photo Importer' and the username 'envision'.
# It is per-user: only the Windows account that saved it can read it back.
# ============================================================================

def _load_password_from_keyring() -> Optional[str]:
    """Fetch the saved Envision password from Windows Credential Manager."""
    try:
        return keyring.get_password(KEYRING_SERVICE, ENVISION_USER)
    except KeyringError as exc:
        LOG.warning("Could not read password from Credential Manager: %s", exc)
        return None


def _save_password_to_keyring(password: str) -> bool:
    """Store the Envision password in Windows Credential Manager.

    Returns True on success, False if the keyring backend rejected the call.
    """
    try:
        keyring.set_password(KEYRING_SERVICE, ENVISION_USER, password)
        return True
    except KeyringError as exc:
        LOG.warning("Could not save password to Credential Manager: %s", exc)
        return False


def load_settings() -> Dict[str, str]:
    """Load saved settings, fetching the password from Credential Manager.

    Also handles the one-time migration from the old plaintext-password
    settings.json schema: if a 'password' field is found in settings.json,
    it's moved into Credential Manager and stripped from the file.
    """
    settings: Dict[str, str] = {}

    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Strip any legacy 'user' field; the username is always
                # ENVISION_USER now.
                data.pop("user", None)
                settings = data
        except Exception as exc:
            LOG.warning("Could not read settings file: %s", exc)

    # Migrate legacy plaintext password (from before keyring integration)
    # into Windows Credential Manager.
    legacy_password = settings.pop("password", None)
    if legacy_password:
        LOG.info(
            "Migrating Envision password from settings.json to Windows "
            "Credential Manager"
        )
        if _save_password_to_keyring(legacy_password):
            # Re-save settings.json without the password field.
            _write_settings_file(settings)
        else:
            # Keyring rejected the write - keep the password in memory for
            # this run so the operator isn't dead in the water.
            settings["password"] = legacy_password
            return settings

    # Fetch the password from Credential Manager.
    pw = _load_password_from_keyring()
    if pw:
        settings["password"] = pw

    return settings


def _write_settings_file(settings: Dict[str, str]) -> None:
    """Write the non-secret settings to settings.json on disk."""
    to_save = {
        k: v for k, v in settings.items()
        if k not in ("user", "password")
    }
    try:
        SETTINGS_FILE.write_text(json.dumps(to_save, indent=2), encoding="utf-8")
    except OSError as exc:
        LOG.warning("Could not save settings file: %s", exc)


def save_settings(settings: Dict[str, str]) -> None:
    """Save settings: password to Credential Manager, the rest to settings.json."""
    password = settings.get("password")
    if password:
        _save_password_to_keyring(password)
    _write_settings_file(settings)


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
# Oracle TNS auto-discovery
# ============================================================================

def _extract_tns_param(body: str, name: str) -> Optional[str]:
    """Find a ``NAME = value`` pattern within a TNS connect-description body."""
    pattern = rf"\b{re.escape(name)}\s*=\s*([^\s)(]+)"
    match = re.search(pattern, body, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def parse_tnsnames(path: Path) -> Dict[str, Dict[str, str]]:
    """Parse a tnsnames.ora file into ``{alias: {host, port, service}}``.

    Tolerant parser: handles balanced parentheses, line comments, multi-alias
    entries (``A, B = ...``), both ``SERVICE_NAME`` and ``SID``, and skips
    malformed entries instead of aborting on them.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    # Strip line comments (# ... end-of-line).
    text = re.sub(r"#[^\n]*", "", text)
    # Strip IFILE directives (we don't follow includes).
    text = re.sub(r"IFILE\s*=\s*[^\n]+", "", text, flags=re.IGNORECASE)

    entries: Dict[str, Dict[str, str]] = {}
    pos = 0
    n = len(text)

    while pos < n:
        # Skip whitespace
        while pos < n and text[pos] in " \t\r\n":
            pos += 1
        if pos >= n:
            break

        # Read alias name(s) up to '=' or '('
        alias_start = pos
        while pos < n and text[pos] not in "=(":
            pos += 1
        alias_raw = text[alias_start:pos].strip()

        # Skip '=' and following whitespace
        if pos < n and text[pos] == "=":
            pos += 1
        while pos < n and text[pos] in " \t\r\n":
            pos += 1

        if pos >= n or text[pos] != "(":
            # Not a real TNS entry; advance to next line and continue.
            while pos < n and text[pos] != "\n":
                pos += 1
            continue

        # Read balanced parentheses
        depth = 0
        body_start = pos
        while pos < n:
            c = text[pos]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    pos += 1
                    break
            pos += 1
        body = text[body_start:pos]

        if not alias_raw:
            continue

        host = _extract_tns_param(body, "HOST")
        port = _extract_tns_param(body, "PORT")
        service = (
            _extract_tns_param(body, "SERVICE_NAME")
            or _extract_tns_param(body, "SID")
        )
        if not (host and port and service):
            continue

        # Handle multi-alias entries like "A, B, C = (...)"
        for alias in (a.strip() for a in alias_raw.split(",")):
            if not re.match(r"^[A-Za-z][\w.\-]*$", alias):
                continue
            entries[alias] = {
                "host": host,
                "port": port,
                "service": service,
            }

    return entries


def find_tnsnames_files() -> List[Path]:
    """Locate every tnsnames.ora file we can find on this machine."""
    found: List[Path] = []

    # 1. Environment variables (most authoritative when set)
    tns_admin = os.environ.get("TNS_ADMIN")
    if tns_admin:
        p = Path(tns_admin) / "tnsnames.ora"
        if p.is_file():
            found.append(p)

    oracle_home = os.environ.get("ORACLE_HOME")
    if oracle_home:
        p = Path(oracle_home) / "network" / "admin" / "tnsnames.ora"
        if p.is_file():
            found.append(p)

    # 2. Common Windows Oracle install roots
    roots: List[Path] = [
        Path(r"C:\app"),
        Path(r"C:\oracle"),
        Path(r"C:\Oracle"),
        Path(r"C:\oraclexe"),
        Path(r"C:\OracleClient"),
        Path(r"C:\OracleInstantClient"),
        Path(r"C:\instantclient"),
        Path(r"C:\Program Files\Oracle"),
        Path(r"C:\Program Files (x86)\Oracle"),
        Path(r"C:\Transact"),
        Path(r"C:\CBORD"),
    ]

    # Also check D:, E:, F:, ... for similarly named folders
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{letter}:\\")
        try:
            if not drive.exists():
                continue
        except OSError:
            continue
        for sub in ("app", "oracle", "Oracle", "OracleClient"):
            roots.append(drive / sub)

    for root in roots:
        if not root.is_dir():
            continue
        try:
            for tns in root.rglob("tnsnames.ora"):
                if tns.is_file():
                    found.append(tns)
        except (PermissionError, OSError):
            continue

    # Deduplicate by resolved path while preserving order.
    seen = set()
    unique: List[Path] = []
    for p in found:
        try:
            rp = p.resolve()
        except (OSError, RuntimeError):
            rp = p
        if rp in seen:
            continue
        seen.add(rp)
        unique.append(p)
    return unique


def discover_oracle_connections() -> List[Dict[str, str]]:
    """Return a deduplicated list of Oracle connections defined on this machine.

    Each dict has keys: ``alias``, ``host``, ``port``, ``service``, ``source``.
    Multiple aliases pointing at the same host:port/service collapse to one.
    """
    files = find_tnsnames_files()
    connections: List[Dict[str, str]] = []
    seen_keys = set()

    for path in files:
        try:
            entries = parse_tnsnames(path)
        except Exception as exc:
            LOG.warning("Failed to parse %s: %s", path, exc)
            continue

        for alias, details in entries.items():
            key = (
                details["host"].lower(),
                str(details["port"]),
                details["service"].lower(),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            connections.append({
                "alias": alias,
                "host": details["host"],
                "port": str(details["port"]),
                "service": details["service"],
                "source": str(path),
            })

    return connections


# ============================================================================
# Setup wizards (interactive only)
# ============================================================================

def setup_wizard(saved: Dict[str, str]) -> Dict[str, str]:
    """Set up the database connection. Tries auto-discovery first."""
    section("Finding your database")
    info("Looking for Oracle settings on this computer...")

    try:
        connections = discover_oracle_connections()
    except Exception as exc:
        LOG.warning("TNS discovery failed: %s", exc)
        connections = []

    if not connections:
        info("Couldn't find Oracle settings automatically on this computer.")
        print()
        return manual_setup_wizard(saved)

    if len(connections) == 1:
        c = connections[0]
        info("Found your database:")
        info(f"  Server:  {c['host']}")
        info(f"  Port:    {c['port']}")
        info(f"  Service: {c['service']}")
        chosen = c
    else:
        info(f"Found {len(connections)} Oracle database(s) on this computer:")
        print()
        for i, c in enumerate(connections, 1):
            print(f"     {i}. {c['alias']}  ->  {c['host']}:{c['port']}/{c['service']}")
        print(f"     {len(connections) + 1}. (None of these - enter settings manually)")
        print()
        choice = ask_choice(
            "Which database do you want to use?",
            max_choice=len(connections) + 1,
            default=1,
        )
        if choice == len(connections) + 1:
            print()
            return manual_setup_wizard(saved)
        chosen = connections[choice - 1]

    print()
    password = ask(
        f"Password for the '{ENVISION_USER}' database account",
        password=True,
    )

    return {
        "server": chosen["host"],
        "port": str(chosen["port"]),
        "service": chosen["service"],
        "password": password,
    }


def manual_setup_wizard(saved: Dict[str, str]) -> Dict[str, str]:
    """Fallback when auto-discovery doesn't find a usable tnsnames.ora."""
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
# Plain-English error explanations (interactive mode only)
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
        info("service name from your Oracle settings.")
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
        info("  - This computer isn't on the office network / VPN, OR")
        info("  - The database server is currently down, OR")
        info("  - Your Oracle settings point to the wrong server.")
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
    conn: "oracledb.Connection",
    files: List[Path],
    quiet: bool = False,
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
        disable=quiet,  # No visual bar in unattended runs (no console).
    )

    try:
        for path in progress:
            try:
                normalized = str(int(path.stem))
            except ValueError:
                LOG.warning("File name is not a number: %s", path.name)
                missing += 1
                if not quiet:
                    progress.set_postfix(done=ok_count, skipped=missing, errors=errors)
                continue
            cust_id = custid_map.get(normalized)
            if cust_id is None:
                LOG.warning("No customer found for: %s", path.name)
                missing += 1
                if not quiet:
                    progress.set_postfix(done=ok_count, skipped=missing, errors=errors)
                continue
            try:
                blob = path.read_bytes()
            except OSError as exc:
                LOG.error("Could not read %s: %s", path, exc)
                errors += 1
                if not quiet:
                    progress.set_postfix(done=ok_count, skipped=missing, errors=errors)
                continue
            batch.append({"cust_id": cust_id, "photo": blob})
            if len(batch) >= BATCH_SIZE:
                written = flush_batch(cur, batch)
                ok_count += written
                errors += len(batch) - written
                batch.clear()
                conn.commit()
                if not quiet:
                    progress.set_postfix(done=ok_count, skipped=missing, errors=errors)
        if batch:
            written = flush_batch(cur, batch)
            ok_count += written
            errors += len(batch) - written
            batch.clear()
            conn.commit()
            if not quiet:
                progress.set_postfix(done=ok_count, skipped=missing, errors=errors)
    finally:
        progress.close()
        cur.close()

    return ok_count, missing, errors


# ============================================================================
# Main flow
# ============================================================================

def _run_app(args: argparse.Namespace) -> int:
    if not args.unattended:
        info("Ready! Let's get started.")
        info("")
        info("This tool copies customer photos into the database.")
        info("Just answer the questions and we'll do the rest.")
        print()

    saved = load_settings()

    # ---- Step 1: connection settings ----
    if args.unattended:
        required = ("server", "port", "service", "password")
        missing_settings = [k for k in required if not saved.get(k)]
        if missing_settings:
            fail(
                "Unattended mode is missing required setting(s): "
                + ", ".join(missing_settings)
            )
            if "password" in missing_settings:
                info("")
                info("The Envision password isn't saved for this Windows user.")
                info("")
                info("To fix this:")
                info("  - Run the tool interactively once as the SAME Windows")
                info("    account that the scheduled task runs as. The password")
                info("    will be saved to that account's Credential Manager.")
                info("  - Then the scheduled task can read it back.")
            else:
                info("Run the tool interactively once first to save them.")
            LOG.error("Unattended run missing required settings: %s", missing_settings)
            return EXIT_BAD_CONFIG
        settings = dict(saved)
        LOG.info("Unattended run using saved settings for server '%s'", settings["server"])
    elif saved.get("server") and saved.get("password"):
        info(f"Last time you connected to '{saved['server']}'.")
        if ask_yes_no("Use the same database settings as last time?", default=True):
            settings = dict(saved)
        else:
            settings = setup_wizard(saved)
    else:
        settings = setup_wizard(saved)

    dsn = f"{settings['server']}:{settings['port']}/{settings['service']}"

    # ---- Step 2: test the connection ----
    if not args.unattended:
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
        if not args.unattended:
            explain_db_error(exc)
        else:
            info(f"  {exc}")
        return EXIT_DB_ERROR

    ok("Connected!")
    save_settings(settings)  # only after a successful connect

    try:
        # ---- Step 3: pick the photo folder ----
        if args.unattended:
            folder = args.folder or saved.get("last_folder")
            if not folder:
                fail("No folder to import from.")
                info(
                    "Use --folder PATH, or run the tool interactively once "
                    "to save a default folder."
                )
                LOG.error("Unattended run missing folder")
                return EXIT_BAD_CONFIG
        else:
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
            if not args.unattended:
                info("Double-check the path and try again.")
            LOG.error("Folder does not exist: %s", folder_path)
            return EXIT_BAD_CONFIG
        settings["last_folder"] = str(folder_path)
        save_settings(settings)
        LOG.info("Importing from folder: %s", folder_path)

        # ---- Step 4: scan ----
        files, duplicates = scan_photo_folder(folder_path)
        if not files:
            print()
            info(f"No .jpg or .jpeg photos were found in {folder_path}")
            if not args.unattended:
                info("Make sure the folder contains photos ending in .jpg or .jpeg")
            LOG.info("No photos found in %s - nothing to do", folder_path)
            return EXIT_OK  # not an error; just nothing to import

        info(f"Found {len(files)} photo(s) in:")
        info(f"  {folder_path}")
        if duplicates:
            info(
                f"({duplicates} extra file(s) shared a customer number with another "
                "and will be skipped.)"
            )
        if not args.unattended:
            print()
            if not ask_yes_no(f"Ready to import these {len(files)} photo(s)?", default=True):
                print()
                info("OK, cancelled. No changes were made.")
                return EXIT_OK

        # ---- Step 5: import ----
        if not args.unattended:
            section("Importing photos")
        else:
            print()
        t0 = time.perf_counter()
        ok_count, missing, errors = import_photos(conn, files, quiet=args.unattended)
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

        LOG.info(
            "Run completed: imported=%d missing=%d errors=%d duplicates=%d elapsed=%.1fs",
            ok_count, missing, errors, duplicates, elapsed,
        )

        return EXIT_OK if errors == 0 else EXIT_PARTIAL_IMPORT
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main() -> int:
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(str(LOG_FILE), encoding="utf-8")],
        force=True,
    )

    if args.unattended:
        LOG.info("Starting unattended run (argv=%s)", sys.argv)

    try:
        return _run_app(args)
    except KeyboardInterrupt:
        print()
        info("Cancelled. No more changes will be made.")
        LOG.warning("Cancelled by user")
        return EXIT_INTERRUPTED
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Unexpected error")
        print()
        fail(f"Something went wrong: {exc}")
        info(f"Details have been saved to: {LOG_FILE.name}")
        return EXIT_GENERIC_ERROR
    finally:
        if not args.unattended:
            try:
                print()
                input("  Press Enter to close this window...")
            except (KeyboardInterrupt, EOFError):
                pass


if __name__ == "__main__":
    sys.exit(main())
