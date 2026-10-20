# Bounty Target Finder

A small local web app that searches public bug bounty programs by in-scope asset
(web, api, android, ios, source code, or any keyword) across **HackerOne, Bugcrowd,
Intigriti and YesWeHack**. Filter by unpaid VDPs or cash bounties, mix or group
results by platform, and export matches to JSON or CSV.

It only reads program listings. It never scans, probes or connects to any target.

## Run it

```bash
git clone https://github.com/Mumer3/bounty-target-finder.git
cd bounty-target-finder
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## How it works

- Program data comes from the open-source
  [bounty-targets-data](https://github.com/arkadiyt/bounty-targets-data) project,
  which refreshes hourly. The app caches each feed for one hour.
- Each platform uses a different JSON schema. `app.py` normalises them: HackerOne
  exposes a boolean for bounties, the others expose payout amounts, so both are handled.
- The server binds to `127.0.0.1` only. If you deploy it publicly, use a production
  server (gunicorn) and add rate limiting.

## Responsible use

- A program appearing here does **not** authorize testing. Read each program's current
  policy and test only assets listed as in scope.
- Data can be stale. Always confirm on the program page.
- Not affiliated with HackerOne, Bugcrowd, Intigriti or YesWeHack. Check the data
  source's license and credit it if you redistribute results.

## Project layout

```
app.py              Flask backend, feed cache, search, export
templates/index.html  The interface
requirements.txt
```
