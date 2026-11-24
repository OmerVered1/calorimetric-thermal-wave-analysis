# CTWA 2.0: analysis inside the desktop app

## Context

Omer runs experiments with the CTWA desktop app (PySide6, lab PC, reached from home over VPN with remote desktop). He analyzes them in the Ångström webapp (Next.js on Vercel, results in Supabase). The only link between the two is a CSV he uploads by hand.

What bothers him:
- moving files by hand;
- working in two programs.

The goal is one desktop app that runs the experiment and analyzes it. When an analysis is saved there, it goes to Supabase, so the webapp updates on its own. The webapp stays online so results can be viewed from any computer, and it keeps its own analysis.

Facts that shape the design:
- The lab PC can reach the internet over HTTPS (the update check works).
- Omer is the only user.
- In the last 120 days, every saved analysis was a sine wave from a one-file CTWA capture: Manual 152, AutoHybrid 23, AutoFit 2.

## Decisions Omer made

| Topic | Decision |
|---|---|
| How | **Rebuild natively in Qt** (Python copy of the maths). He chose this over embedding the web pages in the app. |
| Pages in the desktop app | Analysis, Calibration, Results (Summary, History, **Compare**), **full** Statistics chart builder |
| Analysis modes | All: Manual, AutoFit, AutoHybrid, AutoFFT, Auto, square wave |
| Input | A **Runs** list from the auto-save folder, plus Open… for any one-file CSV. The two-file C80 + Keithley mode is **not** ported. |
| When a run ends | Nothing happens. He picks the run from the Runs list later. |
| Cloud | Results only. Raw CSVs stay on the lab PC (and the NAS copy). |
| Webapp | Keeps analysis. The **webapp maths is the reference**, and the desktop app must match it before any release. |
| Save-route lock | **Fix now**, as its own change (step 0). |
| Delivery | **All at once** as one release, reaching the lab PC by the normal update (Help → Check for updates). |
| Building | **Use subagents** to keep token cost down. |

## Calls I made (Omer can override)

- **Keeping the experiment safe:**
  - The analysis never disturbs a running experiment.
  - Heavy maths runs in a background worker.
  - Errors in the analysis tabs are caught and shown, and never reach the measurement loop.
  - The instrument code is not touched. `tests/test_equivalence_with_original_windows.py` must stay green.
- **Language:** English only. Version **2.0.0**.
- **Saved results:** rows are saved in exactly the shape the webapp saves them:
  - every column;
  - `extra_data` as JSON;
  - `graph_image` as a Plotly `{data, layout}` JSON figure, so web History shows the plot;
  - the same duplicate check as the web.
- **Login and offline saving:**
  - The desktop app saves through the locked `/api/db` route.
  - Omer types the app password once. The app swaps it for a session token and keeps the token in the OS keychain (new dependency `keyring`).
  - Reads use the public anon key, like the webapp.
  - If the internet is down, saves wait in a local queue (app data folder). The queue retries on start, on every save and every 5 minutes, and its status shows in the status bar.
- **Runs list:**
  - It scans `auto_save_path` recursively for CSVs.
  - A run is marked "analyzed" when a saved row's file name matches it.
  - A run still being recorded is listed as "recording" and can't be opened until it ends.
- **Statistics:** chart settings are remembered between sessions (QSettings), replacing the web's settings-in-URL.
- **History plots:** History draws each saved Plotly figure with pyqtgraph, including figures saved by the webapp. Trace types it can't draw are skipped with a note.
- **Charts:** pyqtgraph throughout, with box and violin drawn as custom items, so the app gets no new plotting dependency and keeps one look (CTWA `theme.py`).

## Step 0: lock the webapp's save route (webapp repo, small, now)

**Problem:** `app/api/db/route.ts` inserts, updates and deletes with the service key and checks nothing. `app/api/auth/route.ts` only answers yes or no. `AuthGate.tsx` keeps an `authenticated` flag in sessionStorage.

**Change:**
- **New `lib/session.ts`:**
  - `sessionToken()` = HMAC-SHA256(`APP_PASSWORD`, `"angstrom-session-v1"`) as hex.
  - `isAuthorized(request)` accepts either the `angstrom_session` cookie or `Authorization: Bearer <token>`, compared with `crypto.timingSafeEqual`.
- **`app/api/auth/route.ts`:** on the correct password:
  - sets the cookie (httpOnly, Secure, SameSite=Strict, session-only, matching today's per-tab login);
  - returns `{ ok, token }`, so the desktop app can store the token.
- **`app/api/db/route.ts`:** returns 401 before creating the Supabase client when `!isAuthorized`.
- **`lib/dbClient.ts`:** on a 401, clears `sessionStorage.authenticated` and reloads, so the login screen appears. People logged in before the change re-enter the password once.
- **Effect:** changing `APP_PASSWORD` on Vercel cancels every token.
- **Also check, read-only:** that `analyses`, `setups` and `alpha_presets` have no anon INSERT/UPDATE/DELETE policy (`pg_policies`). Otherwise the lock can be bypassed with the public key. Report what you find; don't change policies without Omer.
- **Verify:**
  - `npx tsc --noEmit` and `next build` pass.
  - A test of the route handler shows: no cookie or token → 401, wrong token → 401, and Supabase is never reached in either case.
  - **Never send an authorized request** to the real database (the standing rule: block `/api/db` in browser tests).
- **Done when:** Omer is asked via the question tool to commit and push (pushing deploys to Vercel).

## Desktop architecture (CTWA repo, branch `desktop-analysis`)

New code. Nothing in `ctwa/instruments/` or the `keithley*_driver.py` files changes.

```
ctwa/analysis/          pure maths, numpy only, no Qt; literal ports of the webapp lib
  parser.py             ← lib/fileParser.ts (one-file paths: CTWA CSV, C80 export; decodeBytes UTF-8→cp1252)
  peaks.py              ← lib/peakDetection.ts
  sine_fit.py           ← lib/sineFit.ts
  modes.py              ← lib/analysis.ts (sync/filter, Auto, Manual, AutoHybrid, AutoFFT, AutoFit,
                           calculateThermalDiffusivity, lag/phase helpers, theoretical curves)
  square.py             ← lib/squareAnalysis.ts
  lag_fit.py            ← lib/lagFit.ts (sqrt / linear / physical models, serialize/describe)
  references.py         ← lib/referenceMaterials.ts, lib/materialColors.ts
  row.py                result → Supabase row + extra_data + Plotly figure (← app/analysis/page.tsx save block ~L900–965)
ctwa/cloud/
  client.py             reads (anon REST), writes (POST {webapp}/api/db with Bearer token), login, keyring
  queue.py              offline upload queue
ctwa/ui/
  runs_tab.py  analysis_tab.py  calibration_tab.py  results_tab.py (Summary/History/Compare)  statistics_tab.py
  plotly_view.py        draws a saved Plotly figure with pyqtgraph
  worker.py             QThreadPool wrapper: run maths off the UI thread, signal results back
```

`ctwa/app.py` `MainWindow` gains the new top-level tabs after Real Time. Its only other change is a Settings entry for the webapp URL and login.

**Literal ports:**
- Keep each TS function's algorithm and order of operations, rather than swapping in scipy equivalents, so the numbers match.
- Page-only logic in `app/analysis/page.tsx` (2,071 lines), `app/calibration/page.tsx` (1,380) and `app/statistics/page.tsx` (1,588) gets ported by reading. Examples: region selection, row building, the duplicate check, calibration application, and the statistics aggregation (mean ± std per period, raw-to-calibrated pairs).

## Proving the two copies give the same numbers

- **Golden generator** in the webapp repo (`ops/golden/generate.ts`, run with `npx tsx`):
  - Calls the webapp's own `lib/` functions on real runs:
    - the 17 Nov Al₂O₃ CTWA CSV;
    - the three fiber captures in `msc results/results why no work/`;
    - one steel run;
    - one square-wave file, if one exists.
  - Covers every mode, with fixed Manual picks.
  - Also covers `fitLagModels` on a set of reference lag points.
  - Writes one JSON per case (inputs + every output field).
- **CTWA test** `tests/test_analysis_matches_webapp.py`:
  - Runs the Python port on the same inputs (stored gzipped in `tests/data/runs/`, ≤10 MB total).
  - Floats must agree to a relative 1e-9; integers and strings exactly.
- **Reference rule:** when the webapp maths changes, regenerate the JSON, and the desktop app must match before release. A short note in both READMEs says so.

## Build order (internal; released once at the end)

| # | Stage | Done when |
|---|---|---|
| 0 | Save-route lock (webapp) | above |
| 1 | Golden generator + `ctwa/analysis/` port | golden test green for every mode |
| 2 | `ctwa/cloud/` | login gets a token; reads work; a save is proven with a mocked server; queue survives restart |
| 3 | Runs + Analysis tabs | open a run → every mode → Save gives a row identical to the web's for the same run (compared against a dry-run row, not a real insert) |
| 4 | Results tabs | Summary filter/edit/delete/CSV export, History plot from web-saved rows, Compare |
| 5 | Calibration tab | reference runs, alpha presets, lag fits match golden, applying calibration produces the web's columns |
| 6 | Statistics tab | every chart type/option from the web page |
| 7 | Release 2.0.0 | full suite green; Omer does one real save from the lab PC and sees it in the webapp; tag `v2.0.0` → installers → Help → Check for updates |

## How the work is split (subagents, as Omer asked)

- **Implementers:** for each stage, a fresh implementer subagent (Sonnet, to save cost) gets a self-contained brief: the TS files to port, the target module, the golden cases, and the rules above. It writes code and tests on `desktop-analysis` and reports back.
- **My role:** I review the diff and test output only, not the whole codebase, and send fixes back to the same subagent. Mechanical, independent ports (e.g. `peaks.py`, `square.py`, `lag_fit.py`) run in parallel.
- **The 2,000-line page ports** (analysis, calibration, statistics) are split into smaller briefs: logic first, then UI.
- **Rules:**
  - Subagents never commit to master, push, tag, or write to Supabase.
  - Every real database write or push goes through Omer via the question tool.
- **Tests:** only the touched area's tests during a stage. The full CTWA suite runs before each stage is accepted and before the release.

## Verification (end to end)

1. **Webapp:** `tsc` and `next build` pass. Unauthorized `/api/db` → 401 (handler test). After Omer's push: logging in and saving in the live webapp still works, done by Omer.
2. **Desktop:**
   - `pytest` is all green, including `test_equivalence_with_original_windows.py` (instrument commands unchanged) and `test_analysis_matches_webapp.py`.
   - Launch in simulation and screenshot each new tab.
   - Analyze the Al₂O₃ run: α, phase and lag must equal the webapp's numbers for the same picks.
3. **Live:** Omer saves one analysis from the lab PC, and it appears in webapp Summary and History with its plot.
4. **Rollout:** after tagging, the GitHub Actions build succeeds and the update check on the lab PC offers 2.0.0.

## Risks

- **Size:** about 7,000 lines of TS (lib + three pages) are being ported. It's large even split into stages.
- **Keeping the copies matched:** two maths copies must stay matched forever. The golden test makes drift visible but doesn't prevent it.
- **Untested on hardware:** the lab-PC save is the first real test of the cloud path. Earlier stages use mocks only, by rule.
