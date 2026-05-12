# Oracle Photo Importer

Bulk-imports customer photos (`.jpg`) into an Oracle 19c `CUSTOMER_PHOTO` table as BLOBs.

Each photo file must be named with the customer's `CUSTOMERNUMBER` (e.g. `1234567.jpg`). The tool resolves each `CUSTOMERNUMBER` to its `CUST_ID` via the `CUSTOMER` table and then writes the file bytes into `CUSTOMER_PHOTO.PHOTO`, also updating `PHOTOMODIFIEDDATE`. If a row already exists for that `CUST_ID`, it is updated; otherwise it is inserted.

## Highlights

- **No Oracle client required.** Uses the modern [`oracledb`](https://python-oracledb.readthedocs.io/) driver in *thin mode*, which connects directly to Oracle 12.1+ (including 19c).
- **Fast.** All customer-number lookups happen in a single batched `IN`-list query, and photo bytes are written via `executemany` with a `BLOB` input hint.
- **Safe.** Uses `MERGE` so the tool is idempotent — re-running on the same directory updates existing photos instead of duplicating them.
- **Visible progress.** A `tqdm` progress bar shows count, rate, ETA, and live counters for OK / missing / errored files.
- **Windows-friendly.** Drop-in `install.bat`, `run.bat`, and an optional `build_exe.bat` to produce a single standalone `photo_importer.exe`.

## Requirements

- Windows 10/11 (also runs on macOS/Linux)
- Python 3.8 or newer ([download](https://www.python.org/downloads/))
- Network access to your Oracle 19c database
- Oracle credentials with `SELECT` on `CUSTOMER` and `INSERT`/`UPDATE` on `CUSTOMER_PHOTO`

## Install (Windows)

1. Clone or download this repo.
2. Double-click `install.bat`. This will:
   - Create a local virtual environment in `.venv\`
   - Install `oracledb`, `tqdm`, and `python-dotenv`
   - Copy `.env.example` to `.env` for you to fill in
3. Edit `.env` and set your Oracle username, password, and DSN:

   ```env
   ORACLE_USER=app_user
   ORACLE_PASSWORD=secret
   ORACLE_DSN=db-host.example.com:1521/ORCLPDB1
   ```

   The DSN format is `host:port/service_name`. Easy Connect strings like `host/service` also work.

## Usage

```bat
run.bat --dir "C:\photos\to_import"
```

Full options:

```
run.bat --dir <DIR> [options]

  --dir, -d DIR         Directory containing .jpg files named <customernumber>.jpg
  --user, -u NAME       Oracle username (overrides ORACLE_USER)
  --password, -p PASS   Oracle password (overrides ORACLE_PASSWORD)
  --dsn DSN             Oracle DSN host:port/service (overrides ORACLE_DSN)
  --ext .jpg            File extension to scan for (default .jpg)
  --batch-size 50       Rows per executemany batch (default 50)
  --dry-run             Scan and look up cust_ids, but make no DB writes
  --log-file PATH       Log file path (default ./photo_importer.log)
  --verbose, -v         Also log to the console
```

Examples:

```bat
REM Try it first — see what would import without writing anything
run.bat --dir "C:\photos" --dry-run

REM Real run
run.bat --dir "C:\photos"

REM Custom DSN, ignore .env
run.bat --dir "C:\photos" --user app --password secret --dsn db.example.com:1521/ORCL
```

### Example output

```
Found 4821 file(s) in C:\photos\to_import
Connecting to Oracle at db.example.com:1521/ORCLPDB1 as app_user...
Looking up cust_ids...
  Matched 4810 of 4821 customer numbers.
Importing: 100%|██████████| 4821/4821 [01:14<00:00, 64.7photo/s, ok=4810, missing=11, err=0]

Done in 74.5s — 4810 imported, 11 unmatched, 0 read errors.
```

## Building a single-file `.exe`

If you'd rather hand teammates a single executable instead of a Python install:

```bat
build_exe.bat
```

The output is `dist\photo_importer.exe`. It still reads `.env` from the working directory.

## How it works

1. **Scan** the target directory for files matching `--ext` (default `.jpg`).
2. **Resolve cust_ids** in chunks of up to 1000 via a single batched query against `CUSTOMER`. Files whose stem isn't a numeric customer number, or whose number doesn't exist, are recorded as *unmatched* and skipped (not fatal).
3. **Import** each photo using `MERGE INTO CUSTOMER_PHOTO` so the tool either inserts a new row or updates the existing one. Photo bytes are bound as `DB_TYPE_BLOB` and flushed in batches.
4. **Commit** at the end of every batch so progress survives interruption.
5. **Log** unmatched / errored files to `photo_importer.log` for review.

## Schema reference

The tool targets the following columns:

| Table             | Column              | Type                       | Notes                              |
|-------------------|---------------------|----------------------------|------------------------------------|
| `CUSTOMER`        | `CUST_ID`           | `NUMBER(10,0)`             | PK — looked up via `CUSTOMERNUMBER`|
| `CUSTOMER`        | `CUSTOMERNUMBER`    | `NUMBER(22,0)`             | Matched against filename stem      |
| `CUSTOMER_PHOTO`  | `CUST_ID`           | `NUMBER(10,0)`             | PK / FK to `CUSTOMER`              |
| `CUSTOMER_PHOTO`  | `PHOTO`             | `BLOB`                     | File bytes written here            |
| `CUSTOMER_PHOTO`  | `PHOTOMODIFIEDDATE` | `TIMESTAMP WITH TIME ZONE` | Set to `SYSTIMESTAMP` on write     |

Thumbnails (`THUMBNAIL`, `THUMBNAILMODIFIEDDATE`) are **not** populated by this tool.

## Troubleshooting

- **`DPY-6005: cannot connect to database`** — Check that the host is reachable (`tnsping`, `ping`, or `Test-NetConnection`) and that the DSN format is `host:port/service`, not `host:port:SID`.
- **`ORA-01017: invalid username/password`** — Verify the `.env` values; the `ORACLE_PASSWORD` line should have no surrounding quotes.
- **Filenames not matched** — Make sure the filename *stem* (without `.jpg`) is exactly the `CUSTOMERNUMBER` value. Leading zeros are stripped automatically since the column is numeric.
- **Slow imports** — Try raising `--batch-size` (e.g. `--batch-size 200`). Very large photos (multi-MB each) are bound up by network throughput, not by the script.
