# Bidding Analytics — Plan (v0.4, 2026-11-03)

Add pages to the ERP that show each employee's daily bidding work and the status of every scraped job, **reading the Google Sheets live through the existing Apps Script web apps. Bid and job data is not stored in the ERP database.**

**Status: implemented (all three phases), 2026-11-03.** Where the build differs from the plan below, §10 says so.

## 1. Decisions (answered 2026-11-03)

| # | Question | Decision |
|---|---|---|
| 1 | How are bids separated per employee? | **One tab per employee** in the applied spreadsheet. Each employee sets a **Bidding profile name** in the ERP, and that name is the tab name (§5). |
| 2 | Proposal status | **Derived by reading both sheets**: the scraper's job list and the employees' applied tabs. No extra stages (interview, rejected, …) for now. |
| 3 | How the ERP reads Google Sheets | **Through the existing Apps Script web apps** (BidExtension `docs/sheets-sync/Code.gs`, job-scraper `apps_script/Code.gs`). No Google Cloud service account. |
| 4 | Daily targets | **None.** |
| 5 | Visibility | **Employees see only their own bidding numbers** (My Bidding) for now. **Everyone can open the Jobs page**, including who bid on each job. Managers/admins see every employee's numbers. Can be widened later. |
| 6 | Spreadsheets | **Separate**: the job list and the applied tabs live in two different spreadsheets, so every tab in the applied spreadsheet is a candidate employee tab. |
| — | Storage | **No bid/job data in the database.** The ERP pulls from the sheets on demand and keeps only a short in-memory cache. The only new column is each employee's Bidding profile name (configuration). |

## 2. Sources

| Sheet | Read through | Columns used |
|---|---|---|
| **Job list** (job-scraper): tabs `US - Software`, `US - ML/AI`, `US - Data`, `US - DevOps/SRE`, `EU - …` | job-scraper web app, existing `read_columns` action (5,000 rows per call) | `key, title, company, country, remote, skill_level, salary, ats, is_recruiter, posted_at, first_seen, url` — region and role come from the tab name |
| **Applied** (BidExtension, separate spreadsheet): one tab per employee, tab name = the employee's Bidding profile name | BidExtension web app, **two new read-only actions** (§3) | `Date, Title, Link, Company, Location, Salary, ResumeNo, Score` |

## 3. Change to BidExtension `docs/sheets-sync/Code.gs` (additive)

Today the only read action is `listPending`, which returns just the Link of rows that haven't been filled in yet. That isn't enough for analytics, so add:

- `listTabs: true` → `{ success, tabs: [{ name, rows }] }` — every tab in the spreadsheet.
- `readTabs: true | ["Tab A", …]` → `{ success, tabs: [{ name, header, rows }], missing }` — every tab (or the named ones) in **one call**. Each row is keyed by header text, plus `row` and a computed `status` (`pending` / `applied`, same rule as `listPending`). Dates come back as `yyyy-MM-dd`, and Link is the real URL. **Implemented 2026-11-03**, see `SETUP.md` → "ERP read access".

Both actions check the same `SHARED_SECRET`, only read, and **never create a tab**. `getOrCreateSheet` would create one, so they must not use it. Existing `test`, `job` and `listPending` behaviour is unchanged, so the extension keeps working as is. After the edit: **Deploy → Manage deployments → Edit → New version**, so the URL stays the same.

The job-scraper's `Code.gs` needs no change. Note that its `getSheet_` creates a tab if the name doesn't exist, so the ERP only asks for the tab names configured in the ERP (§6).

## 4. How status is worked out (joining the two sheets)

Jobs are matched by **normalized URL**: lowercase host, no `utm_*`/`gclid`/`fbclid`/`ref` parameters, no fragment and no trailing `/`, the same idea as the extension's `normalizeUrlForCache`. When the URLs don't match, the ERP falls back to **company + title** (port of `job_scraper/scrape.job_identity`).

| Where the job is found | Status shown |
|---|---|
| In the job list, not in any employee tab | **Not bid** |
| In an employee tab, only `Link` filled | Queued for Auto-Bid, not applied to yet: **left out of every page** |
| In an employee tab, row filled after "Mark as Applied" | **Applied** — by *employee*, on *Date*, with *Score* and *ResumeNo* |
| In an employee tab, not in the job list | **Applied — found outside the scraper**, or the job was already pruned from the job list |
| In more than one employee tab | Flagged **duplicate bid** |

## 5. Backend (FastAPI, new module `app/modules/bidding`)

```
bidding/
  sheets_client.py   web-app client; ports job-scraper's WebAppClient (Apps Script 302 →
                     /macros/echo redirect handling and retries) for both web apps
  normalize.py       url_norm() and job_identity(), with unit tests built from real sheet rows
  snapshot.py        fetch both sheets → in-memory snapshot: scraped jobs, bids, joined statuses
  service.py         aggregations for the pages (per day, per employee, per region/role, …)
  router.py          endpoints below
```

**Caching (in memory, not the database):** the API keeps one snapshot for **5 minutes**, configurable. Pages show "Data as of 10:42 · Refresh", and Refresh forces a new pull. If both web apps fail, the last snapshot is shown with a warning. Concurrent requests share one in-flight fetch. Reads are kept small: only the needed columns, and the job-list tabs are fetched in 5,000-row pages.

**Employee ↔ tab: Bidding profile name.** Each employee has a **Bidding profile name** in the ERP. It must equal the **Sheet Tab Name** they typed in the extension (Profile → Settings → Google Sheets Sync), which is the tab their bids go to.

- Stored as one new nullable column `employees.bidding_profile_name`, unique ignoring case. This is configuration, not bid data, and it needs migration `0010_employee_bidding_profile.py`.
- **The employee sets it themselves** on **My Bidding → Profile**, through `PUT /api/bidding/me/profile`. That endpoint only touches their own row, so it needs no general employee-edit permission. Admins and anyone with `employees.manage` can also set it on the employee page.
- The form shows a dropdown of tab names found in the applied spreadsheet (from `listTabs`) that no other employee has claimed. Free text is allowed for a tab that doesn't exist yet, and it fills in on the first "Mark as Applied". The form also shows whether the tab exists and how many rows it has.
- Matching ignores case and extra spaces. Tabs nobody has claimed are listed as **"Unclaimed tabs"** on the Sources page and left out of per-employee numbers, but they still count as bids on the Jobs page, labelled with the tab name.
- If a tab is renamed in Sheets, the employee updates their profile name, or the other way round. Nothing else has to change.

**Configuration** (not bid data): web app URLs, secret and token, the job-list tab names (default: the eight tabs) and the data age limit (default 5 minutes), all set in the app under Settings → Bidding Sheets.

**Endpoints**

```
GET  /api/bidding/summary?from&to&employee_id     totals + per-day series (scope-filtered)
GET  /api/bidding/daily?date                      per-employee rows for one day
GET  /api/bidding/employees/{id}?from&to          one employee's stats
GET  /api/bidding/bids?employee_id&status&from&to&q&score_min&score_max&page
GET  /api/bidding/jobs?region&role&ats&status&first_seen_from&first_seen_to&q&page
GET  /api/bidding/sources                         web-app health, tabs found, unclaimed tabs, data age
GET  /api/bidding/me/profile                      my profile name, tab found?, row count, free tabs
PUT  /api/bidding/me/profile  {profile_name}      set my profile name (own row only)
PUT  /api/bidding/employees/{id}/profile          admin / employees.manage
POST /api/bidding/refresh                         drop the cache and pull again
GET  /api/bidding/export/{bids|daily}.csv         via core/csv_export.py
```

**Permissions** (`rbac/permissions.py`): `bidding.read` with scopes OWN / ALL. Defaults: Employee = OWN, Project Manager = ALL, Admin = all. Permissions are code-defined, so there is no schema change. The grant goes onto the already-seeded roles through *Settings → Roles & Permissions*, or a small data migration. With OWN scope, the summary, daily, employee and bids endpoints filter to the signed-in user's own tab. **`/jobs` is not scope-filtered**: everyone with `bidding.read` sees every job, its status, and who bid on it.

## 6. Pages (new nav section "Bidding")

| Page | Route | Who | Content |
|---|---|---|---|
| **My Bidding** | `/bidding/me` | everyone with `bidding.read` | Today: applied, average score. Bids per day over the last 30/90 days, score distribution, resumes used, a list of my bids with filters. **Profile** tab to set the Bidding profile name. If no name is set yet, the page opens on the Profile tab. |
| **Overview** | `/bidding` | ALL | Today and this week: bids, active bidders, average score, scraped jobs, % of scraped jobs bid. Chart of scraped jobs vs bids per day. Table of employees × last 14 days with bid counts per cell. |
| **Daily Report** | `/bidding/daily` | ALL | Pick a date. Per employee: applied, average/min/max score, resumes used. Click through to that employee's bids that day. CSV export. |
| **Employee** | `/bidding/employees/[id]` | ALL (OWN → redirects to My Bidding) | Same as My Bidding for one employee. Also linked from the employee profile. |
| **Jobs** | `/bidding/jobs` | **everyone** with `bidding.read` | All scraped jobs with a **Status** column (Not bid / Applied · name). Filters: region, role, ATS, skill level, remote, recruiter, first-seen dates. "Not bid yet" quick filter. Duplicate-bid flag. |
| **Sources** | `/settings/bidding-sources` | admins | Both web apps' health, tabs found, rows per tab, which employee claimed each tab, unclaimed tabs, employees with no profile name, last fetch time and error, Refresh. |

Built with the existing `components/charts/charts.tsx` (Recharts), `components/erp/data-table.tsx` and `export-menu.tsx`. Nav entries go in `lib/nav.ts` with `anyOf: ["bidding.read"]`.

## 7. Limits of reading live (accepted with this design)

- **Job-list history is only as long as the scraper keeps it**: `prune_after_days = 30`. "Scraped per day" and "% bid" can't go further back than that. Bids history is complete, because the applied tabs are never pruned. *If longer history is needed later:* raise `prune_after_days`, or add the database snapshot from plan v0.1.
- **Numbers follow the sheet.** Editing or deleting rows in Sheets changes past reports.
- **First page load after the cache expires is slower.** It's mostly the job-list tabs, which are read 5,000 rows per call and one call at a time, because the script uses a lock. With current tab sizes this is a few seconds to tens of seconds. The 5-minute cache and Refresh button cover it. If it gets too slow, the API can refresh the snapshot in the background before it expires.
- **`Date` is a UTC date** (the extension uses `toISOString()`). For a team in America/Chicago, bids after 6 pm local time show on the next day. Fix in the extension: write the local date. It's a one-line change, recommended.
- **The Bidding profile name must equal the extension's Sheet Tab Name**, or the employee's bids show as an unclaimed tab.

## 8. Phases

**Phase 1 — Read the sheets** · ~2 days
`Code.gs` actions `listTabs` / `readTabs` + redeploy; `sheets_client.py`, `normalize.py`, `snapshot.py` with tests; migration `0010` (`employees.bidding_profile_name`); profile endpoints + Profile tab; `/sources`, `/refresh`; Sources page. *Done when:* every employee has claimed their tab, the Sources page shows no unclaimed tabs, and row counts equal the sheets.

**Phase 2 — Employee and daily pages** · ~3 days
`bidding.read` permission, My Bidding, Overview, Daily Report, Employee page, CSV export, nav. *Done when:* an employee sees only their own bids, and a manager can see who bid how much on any day.

**Phase 3 — Jobs and status** · ~2 days
Jobs page with joined status, "Not bid yet", duplicate-bid flags, unmatched-link report. Also the extension's local-date fix.

Each phase runs the repo's checks: `pytest`, `ruff`, `alembic check`, web `typecheck` / `lint` / `test` / `build`, `npm run gen:api`.

## 9. Still to confirm

Nothing blocking. Open for later: whether employees should also see team-wide numbers (leaderboard), and whether to keep longer job-list history (§7).

## 10. What was built

**API** (`apps/api/app/modules/bidding/`, all under `/api/v1/bidding`):

| File | Role |
|---|---|
| `sheets.py` | Clients for both web apps (stdlib `urllib`, the Apps Script redirect handling and retries from job-scraper) |
| `normalize.py` | `url_key` (port of the extension's `normalizeUrlForCache`), `job_identity` (port of the scraper's), tab-name matching, cell parsing |
| `snapshot.py` | Builds the joined picture: bids → jobs by URL, then company + title; leaves out links only queued for Auto-Bid; duplicates |
| `cache.py`, `deps.py` | In-memory snapshot, one shared fetch, keeps the last good data when a sheet fails. A background task started with the API reads the sheets at startup and at each age limit, so requests answer from memory |
| `service.py`, `schemas.py`, `router.py` | Numbers and endpoints: `stats`, `daily`, `bids`, `jobs`, `/export` for daily (CSV/Excel/PDF) and bids (CSV/Excel); export the job list from its Google Sheet, `me/profile`, `employees/{id}/profile`, `sources`, `refresh` |

- Employees: an employee can have **several** bidding profile names (tabs), each owned by one employee at most. Table `employee_bidding_profiles` (name unique, case-insensitive), migration `0012`, which replaces the single column added in `0010_bidding.py`. Reports group by employee, adding their tabs together; a tab nobody has claimed is its own row. `0010` also grants `bidding.read` to the existing Employee (own) and Project Manager (all) roles.
- Permissions: `bidding.read` (own / all) and **`bidding.manage`** (all; Sources page and setting other people's profile names). Administrators hold both.
- Connections: set in the app under **Settings → Bidding Sheets → Connections** (URL, secret/token, job-list tabs, cache minutes; with Test buttons). Stored in the `bidding_settings` table (migration `0011`, `models.py`, `store.py`); secrets are write-only and kept out of the audit log; only `script.google.com/…/exec` URLs are accepted, and a saved secret is only sent to the URL it was saved with. Endpoints: `GET/PUT /bidding/settings`, `POST /bidding/settings/test`.

**Web** (`apps/web/src`): nav section *Bidding* with My Bidding (`/bidding/me`, Overview + Profile tabs), Team Overview (`/bidding`), Daily Report (`/bidding/daily`, a date range with each person's top 3 resumes), **All Bids** (`/bidding/bids`, added), Job List (`/bidding/jobs`, `?status=not_bid`), one employee (`/bidding/employee?id=…`: a query string instead of `/bidding/employees/[id]`, to keep the folder depth the desktop sync can handle), and Settings → Bidding Sheets (`/settings/bidding`). Team pages are shown only with `bidding.read` scope *all* (new `allScope` on nav items). Bidding types live in `lib/bidding.ts`, written by hand; they can be replaced with generated ones after `npm run gen:api`.

**Extension**: `docs/sheets-sync/Code.gs` gained the read-only `listTabs` / `readTabs` actions. `background.js` now dates a bid with the browser's local date instead of the UTC date.

**Tests**: `tests/test_bidding_logic.py` (no database: matching, web-app clients, joining, cache, numbers) and `tests/test_bidding_api.py` (scopes, profile names, exports, sheet errors), sharing rows shaped like the web apps' responses in `tests/bidding_fixtures.py`.
