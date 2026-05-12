# Customer Photo Importer

A tool that copies a folder of customer photos from your computer into the Oracle database, so the photos show up on each customer's record in the system.

## What you need before you start

1. **A Windows computer** (Mac and Linux work too, but this guide is written for Windows).
2. **Python** installed on the computer. If it isn't, the tool tells you exactly how to get it (it's free and takes about 2 minutes).
3. **Your database login** — the server address, your username, and your password. Your database administrator can give you these if you don't know them.
4. **A folder full of photos.** Each photo file has to be named with the customer's number plus `.jpg` or `.jpeg`. For example, customer number `1234567` would be saved as `1234567.jpg` (or `1234567.jpeg` — both work).

## How to install (just once)

1. On this page, click the green **`Code`** button, then **`Download ZIP`**.
2. Find the ZIP file you just downloaded (usually in your **Downloads** folder) and unzip it. Putting the unzipped folder on your Desktop is a good choice.
3. Open the folder.
4. Double-click **`Start Photo Importer`**.
5. The first time you run it, the tool sets itself up. This takes about a minute. Don't close the window while it's working.

That's the whole install. After that, just double-click **`Start Photo Importer`** any time you want to import photos.

## How to use it

Double-click **`Start Photo Importer`**.

The tool asks a few simple questions:

1. **The first time only:** it asks for your database server, port, service name, username, and password. After that, it remembers them and just asks *"Use the same settings as last time?"*.
2. **It tests your login.** If something is wrong, it tells you exactly what to check in plain English.
3. **A pop-up window opens** so you can browse to the folder with your photos. Click the folder and click **Select Folder**.
4. **It tells you how many photos it found** and asks if you want to go ahead.
5. **It imports the photos** and shows you a progress bar with how many are done, how long is left, and how many were skipped (if any).
6. **It shows a summary** when it's done.

Press Enter to close the window when you're finished.

## What if something goes wrong?

The tool explains common problems in plain English. The most likely ones:

- **"Could not connect to the database"** — You may not be connected to the office network or VPN. Check that first. Also double-check the server name and port.
- **"Username or password is wrong"** — Type them again carefully. The password letters are hidden as you type, so typos are easy.
- **"None of the photo file names match any customer numbers"** — Check that each photo's file name is just the customer's number, like `1234567.jpg`. Names with letters in them, or extra words, won't work.

If something else goes wrong, the tool writes the technical details to a file called **`photo_importer.log`** in the same folder. If you need help, send that file to your IT person.

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

After your first run, the tool remembers your database settings (including the password) in a file called `settings.json` in the same folder as the tool.

**Keep this file private** — it contains your database password. Don't share the folder with anyone you wouldn't share your password with. To clear your saved settings, just delete `settings.json` and the tool will ask for everything again next time.

## Re-running on the same photos

It's safe to run the tool again on the same folder. If a customer already has a photo, the tool just updates it with the newer one — it doesn't create duplicates. So if you're not sure whether something imported, just run it again.

---

## For IT / technical staff

This tool is built in Python 3 using [`oracledb`](https://python-oracledb.readthedocs.io/) in *thin mode*, so no Oracle Instant Client needs to be installed on the operator's machine. It works against Oracle 12.1 and newer, including 19c.

**How it works:**

- `Start Photo Importer.bat` finds Python (or walks the user through installing it), creates a `.venv\`, installs `oracledb` and `tqdm`, then launches `photo_importer.py`.
- The Python script is fully interactive: it prompts for credentials, opens a tkinter folder-picker dialog, and saves answers (yes, including the password) to `settings.json` so subsequent runs only need a single confirmation.
- File scanner accepts both `.jpg` and `.jpeg` (case-insensitive). They contain identical JPEG image data, so no conversion is performed — the bytes are written directly as a BLOB.
- If two files resolve to the same customer number (e.g. `1234567.jpg` and `1234567.jpeg`, or `001234.jpg` and `1234.jpeg`), the `.jpg` variant wins and the other is logged and skipped.
- Customer-number lookups against `CUSTOMER.CUSTOMERNUMBER` are done in chunks of up to 1000 in a single query each.
- Photos are written into `CUSTOMER_PHOTO` via a `MERGE` statement so re-runs update existing rows instead of failing on the primary key.
- `PHOTO` is bound as `DB_TYPE_BLOB`. Writes happen via `executemany` in batches of 50, with a per-row fallback if a batch fails so a single bad file can't poison the whole batch. `conn.commit()` runs after every batch so progress survives an interruption.
- `PHOTOMODIFIEDDATE` is stamped to `SYSTIMESTAMP` on every write. The `THUMBNAIL` / `THUMBNAILMODIFIEDDATE` columns are not touched.
- All warnings and errors are written to `photo_importer.log`. The console stays clean for the progress bar.

**Distributing without Python:**

If you'd rather hand teammates a single `.exe`, run `build_exe.bat` (after `Start Photo Importer.bat` has been run at least once to set up the venv). The output is `dist\photo_importer.exe` — a standalone binary that still uses `settings.json` from the working directory.

**Required Oracle privileges:**

- `SELECT` on `CUSTOMER`
- `INSERT`, `UPDATE` on `CUSTOMER_PHOTO`
