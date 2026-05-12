# Customer Photo Importer

A tool that copies a folder of customer photos from your computer into the Oracle database, so the photos show up on each customer's record in the system.

## Quick start

**You don't need to install anything.** Just:

1. **Download the tool.** Click this link to get the latest version:  
   👉 **[Download Customer Photo Importer](https://github.com/joker5914/oracle-photo-importer/releases/download/rolling/Customer.Photo.Importer.exe)**

2. **Find it in your `Downloads` folder** and double-click **`Customer.Photo.Importer.exe`**.

3. Windows may show a blue *"Windows protected your PC"* warning the first time. That's normal for any program from the internet. Click **More info**, then **Run anyway**.

The tool opens in a window and walks you through everything from there.

## What you need before you start

- **The Envision database password.** The tool always logs in as the shared **`envision`** account, so you don't need to enter a username — just the password. Anyone on your team who uses this tool should already know it; if not, ask your database administrator.
- **A folder full of photos.** Each photo file has to be named with the customer's number plus `.jpg` or `.jpeg`. For example, customer number `1234567` should be saved as `1234567.jpg` (or `1234567.jpeg` — both work).

The tool finds your database settings automatically by looking for the Oracle client that's already installed on this computer. If it can't find one, it'll ask you for the server address, port, and service name. Your IT person can tell you those.

## How to use it

Double-click **`Customer.Photo.Importer.exe`**.

The tool asks a few simple questions:

1. **The first time only:** it scans this computer for the Oracle settings (server, port, service name). When it finds them, it just asks for the Envision password. If multiple databases are configured, it shows a numbered list so you can pick the right one. After that, it remembers your choice and just asks *"Use the same settings as last time?"*.
2. **It tests your login.** If something is wrong, it tells you exactly what to check in plain English.
3. **A pop-up window opens** so you can browse to the folder with your photos. Click the folder and click **Select Folder**.
4. **It tells you how many photos it found** and asks if you want to go ahead.
5. **It imports the photos** and shows you a progress bar with how many are done, how long is left, and how many were skipped (if any).
6. **It shows a summary** when it's done.

Press Enter to close the window when you're finished.

## What if something goes wrong?

The tool explains common problems in plain English. The most likely ones:

- **"Could not connect to the database"** — You may not be connected to the office network or VPN. Check that first.
- **"Password for the 'envision' account is wrong"** — Type it again carefully. The password letters are hidden as you type, so typos are easy. If the Envision password was recently changed, use the new one.
- **"Couldn't find Oracle settings automatically"** — The tool couldn't locate a `tnsnames.ora` file on this computer. It'll fall back to asking you for the server, port, and service name. Your IT person can provide them.
- **"None of the photo file names match any customer numbers"** — Check that each photo's file name is just the customer's number, like `1234567.jpg`. Names with letters in them, or extra words, won't work.

If something else goes wrong, the tool writes the technical details to a file called **`photo_importer.log`** right next to the .exe. If you need help, send that file to your IT person.

## Naming your photos

The tool finds each customer by looking at the photo's file name. The file name has to be the customer's `customernumber` value, followed by `.jpg` or `.jpeg`. Capitalization doesn't matter — `.JPG` and `.JPEG` work too.

| File name           | Works?       | Why                                                            |
|---------------------|--------------|----------------------------------------------------------------|
| `1234567.jpg`       | Yes          | Just the customer number plus `.jpg`                           |
| `1234567.jpeg`      | Yes          | `.jpeg` works exactly the same as `.jpg`                       |
| `9876543.JPG`       | Yes          | Capitalization doesn't matter                                  |
| `John_Smith.jpg`    | No           | The name isn't a number                                        |
| `cust_1234567.jpg`  | No           | Has extra text in front of the number                          |
| `1234567.png`       | No           | Must end in `.jpg` or `.jpeg`                                  |

If you happen to have two files for the same customer (like `1234567.jpg` **and** `1234567.jpeg`), the tool keeps one and skips the other so you don't accidentally upload the same person's photo twice. It tells you in the summary if this happened.

## Where your settings are saved

After your first run, the tool remembers your database settings (including the Envision password) in a file called `settings.json` next to the .exe.

**Keep this file private** — it contains the Envision password. Don't share the folder with anyone you wouldn't share that password with. To clear your saved settings, just delete `settings.json` and the tool will ask for everything again next time.

## Re-running on the same photos

It's safe to run the tool again on the same folder. If a customer already has a photo, the tool just updates it with the newer one — it doesn't create duplicates. So if you're not sure whether something imported, just run it again.

## Running automatically (Windows Task Scheduler)

You can have Windows Task Scheduler run the importer for you on a schedule — say, every morning at 2am, or every hour. Here's how to set it up.

### Step 1: Run the tool interactively at least once

Run **`Customer.Photo.Importer.exe`** normally and let it import a folder of photos successfully. This saves your database settings (server, port, service name, Envision password) and the folder you picked. The scheduled task will reuse all of that.

### Step 2: Put the .exe somewhere permanent

Move `Customer.Photo.Importer.exe` to a folder you won't accidentally clean up later — something like `C:\Tools\PhotoImporter\`. Make sure `settings.json` (created in step 1) lives in the same folder.

### Step 3: Create the scheduled task

1. Open **Task Scheduler** (search for "Task Scheduler" in the Start menu).
2. In the right-hand panel, click **Create Basic Task...**
3. **Name:** *"Customer Photo Import"* (or whatever you like). Click **Next**.
4. **Trigger:** Pick how often you want it to run (daily, weekly, on log-on, etc.). Click **Next**, set the time, and click **Next** again.
5. **Action:** *"Start a program"*. Click **Next**.
6. **Program/script:** the full path to the .exe, for example:
   ```
   C:\Tools\PhotoImporter\Customer.Photo.Importer.exe
   ```
7. **Add arguments (optional):** to make it run without any prompts, type:
   ```
   --unattended --folder "C:\incoming\photos"
   ```
   The `--unattended` flag tells the tool to skip all the prompts and use your saved settings. The `--folder` part is optional — if you leave it off, the tool will import from whatever folder you imported last time.
8. Click **Next**, review the summary, then click **Finish**.

That's it. The task will run on its schedule using the database settings you saved in step 1.

### Where to see what happened

After each scheduled run, the tool writes to **`photo_importer.log`** in the same folder as the .exe. Open that file to see how many photos were imported, how long it took, and whether anything failed.

For extra confidence, right-click the task in Task Scheduler and choose **Run** to trigger it on demand. Then check the log.

### Command-line reference

```
Customer.Photo.Importer.exe [--unattended] [--folder PATH]

Options:
  --unattended, --auto, -y    Run with no prompts. Requires saved settings
                              from a previous interactive run.
  --folder PATH, -f PATH      Override the photo folder. Optional - if not
                              provided, the tool uses the last folder it
                              imported from.
```

Run `Customer.Photo.Importer.exe --help` for a full list of options.

### Exit codes

Useful if you want Task Scheduler to react differently to success vs failure (for example, send an email only on failure):

| Code | Meaning                                              |
|------|------------------------------------------------------|
| 0    | Success (including "folder was empty, nothing to do") |
| 1    | Unexpected error — check `photo_importer.log`        |
| 2    | Missing settings, or `--folder` path doesn't exist   |
| 3    | Could not connect to the database, or login failed  |
| 4    | Import ran, but some individual photos failed       |
| 130  | Cancelled by user (Ctrl+C)                          |

---

## For IT / technical staff

This tool is built in Python 3 using [`oracledb`](https://python-oracledb.readthedocs.io/) in *thin mode*, so no Oracle Instant Client needs to be installed on the operator's machine to make the connection (though one is required for `tnsnames.ora` auto-discovery to find anything useful). It works against Oracle 12.1 and newer, including 19c.

### Auto-discovery of Oracle settings

On first run, the tool resolves the database connection details automatically using this lookup chain:

1. `%TNS_ADMIN%\tnsnames.ora`
2. `%ORACLE_HOME%\network\admin\tnsnames.ora`
3. Recursive scan of common Windows Oracle install roots: `C:\app`, `C:\Oracle`, `C:\oracle`, `C:\oraclexe`, `C:\OracleClient`, `C:\OracleInstantClient`, `C:\instantclient`, `C:\Program Files\Oracle`, `C:\Program Files (x86)\Oracle`, `C:\Transact`, `C:\CBORD`, and the same on other fixed drive letters.

For each `tnsnames.ora` found, a tolerant parser extracts `HOST`, `PORT`, and `SERVICE_NAME` (or `SID`) from every connect descriptor it can parse. Multi-alias entries (`A, B = (...)`) are expanded, and connections that resolve to the same `host:port/service` are collapsed. If there's exactly one connection, it's used silently; if multiple, the operator picks from a numbered list. If none, the tool falls back to a manual setup wizard.

Resolved settings are saved to `settings.json` (next to the .exe), so subsequent runs skip discovery entirely.

### Unattended mode

When `--unattended` (or `--auto`, or `-y`) is on the command line:

- **Argv is pre-scanned at module load** before the loading banner prints, so unattended runs don't pollute Task Scheduler logs with interactive UI noise.
- **All interactive prompts are skipped.** The tool reads the connection settings out of `settings.json`; if any of `server`, `port`, `service`, or `password` are missing it exits with code 2 and a clear log message instead of prompting.
- **No folder picker.** The folder comes from `--folder` if provided, otherwise from `settings.last_folder`. If neither exists, exit 2.
- **No "ready to import?" confirmation.** The tool proceeds as soon as it has a folder.
- **The `tqdm` progress bar is disabled** (`disable=True`), since Task Scheduler may run without an attached console.
- **No final "Press Enter to close" pause.** The process exits cleanly so Task Scheduler can record the exit code.

An empty folder is treated as success (exit 0), since for a recurring task that's the normal "nothing new to import" case.

### Distribution

The `.github/workflows/build.yml` GitHub Actions workflow runs on every push to `main` and:

1. Sets up Python 3.12 on a `windows-latest` runner.
2. Installs `oracledb`, `tqdm`, `cryptography`, and `pyinstaller`.
3. Bundles the script with `pyinstaller --onefile --name "Customer Photo Importer" --collect-all oracledb --collect-all cryptography photo_importer.py`.
4. Publishes the resulting `.exe` to the **`rolling`** release, marked as Latest.

Operators always download from:

```
https://github.com/joker5914/oracle-photo-importer/releases/download/rolling/Customer.Photo.Importer.exe
```

Note: GitHub converts spaces in release asset filenames to dots in the URL slot (even though the GitHub UI shows the asset name with spaces). So PyInstaller's output of `Customer Photo Importer.exe` becomes `Customer.Photo.Importer.exe` in any direct-download URL.

To build the same `.exe` locally, run `build_exe.bat` (after `Start Photo Importer.bat` has been run at least once to set up the venv). The output is `dist\Customer Photo Importer.exe`.

### Running from source

Clone the repo, double-click `Start Photo Importer.bat`. It creates a `.venv\`, installs dependencies, and launches `photo_importer.py`. Requires Python 3.8+ on the operator's `PATH`. CLI flags work identically when running from source:

```
python photo_importer.py --unattended --folder "C:\incoming\photos"
```

### How it works

- The Oracle username is hardcoded to **`envision`** (constant `ENVISION_USER` at the top of `photo_importer.py`). To change the account, edit that single line.
- The Python script is fully interactive by default: it auto-discovers Oracle settings (see above), prompts for the `envision` password, opens a tkinter folder-picker dialog, and saves the answers to `settings.json` so subsequent runs only need a single confirmation. With `--unattended`, every prompt is skipped and the tool fails fast on missing settings.
- When running as a PyInstaller bundle, `settings.json` and `photo_importer.log` live next to the .exe (resolved via `sys.executable`), not in the temporary unpacked directory.
- A loading banner prints at the top of `photo_importer.py` before any heavy imports, so the operator sees friendly text the instant Python starts (avoiding the appearance of a frozen console while the .exe unpacks itself). The banner is suppressed in unattended mode.
- File scanner accepts both `.jpg` and `.jpeg` (case-insensitive). They contain identical JPEG image data, so no conversion is performed — the bytes are written directly as a BLOB.
- If two files resolve to the same customer number (e.g. `1234567.jpg` and `1234567.jpeg`, or `001234.jpg` and `1234.jpeg`), the `.jpg` variant wins and the other is logged and skipped.
- Customer-number lookups against `CUSTOMER.CUSTOMERNUMBER` are done in chunks of up to 1000 in a single query each.
- Photos are written into `CUSTOMER_PHOTO` via a `MERGE` statement so re-runs update existing rows instead of failing on the primary key.
- `PHOTO` is bound as `DB_TYPE_BLOB`. Writes happen via `executemany` in batches of 50, with a per-row fallback if a batch fails so a single bad file can't poison the whole batch. `conn.commit()` runs after every batch so progress survives an interruption.
- `PHOTOMODIFIEDDATE` is stamped to `SYSTIMESTAMP` on every write. The `THUMBNAIL` / `THUMBNAILMODIFIEDDATE` columns are not touched.
- All warnings and errors are written to `photo_importer.log`. The console stays clean for the progress bar.

### Required Oracle privileges (for the `envision` account)

- `SELECT` on `CUSTOMER`
- `INSERT`, `UPDATE` on `CUSTOMER_PHOTO`
