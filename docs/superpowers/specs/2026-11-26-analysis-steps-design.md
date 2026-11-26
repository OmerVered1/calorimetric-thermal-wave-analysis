# Analysis tab in steps, like the webapp (short design)

**Date:** 2026-11-26 · **Asked by:** Omer ("the analysis on the app doesn't have the
same workflow the webapp analysis has and it doesn't have the source and response
period separated")

## Intent
Omer analyzes in the desktop app now and wants the webapp's step-by-step flow
instead of the one screen 2.0 has. He also wants the source and response period
shown separately.

## Decisions (Omer's, question tool, 26 Nov)
- **Steps, one at a time**, with a step bar and Back/Next (not one long page).
- **Peaks step** (Manual mode only) shows **only the region, zoomed**, like the web.
- **Sample details** (Sample, date, time, devices, temperature, gas) are filled
  in at **step 1 Setup**, like the web. Results only has Save.
- Not wanted now: web-style grouped results, the α-vs-period peers chart.
  The results list stays as it is, plus the periods below.
- **Periods:** results show Source Period T, Response Period T, Source
  Frequency f and Response Frequency f (web labels). The response values are
  already calculated and saved; they were only missing from the list.

## Approaches considered
1. **Paged steps inside the Analysis tab** (chosen): a step bar over the
   existing plot and a stacked bottom panel. Reuses the plot, settings,
   results and save code.
2. Steps stacked on one long page that fold, as the web does. Rejected:
   Omer asked for one step at a time.
3. A pop-up wizard window. Rejected: modal, it would block the main window
   while a run records.

## Design
```
 ① Setup ── ② Region ── ③ Peaks ── ④ Results        (③ only in Manual mode)
```
- **① Setup:** no plot. The run's file name and start, the sample form
  (pre-filled from the run header's experiment details, as now), and the
  analysis settings (mode, wave, smoothing, r₁, r₂, calibration, lag).
  **Next: Region →** (enabled once the run has loaded).
- **② Region:** the whole-run plot with the draggable region; markers hidden.
  A bar shows `Region 1200 – 5400 s`, **← Back**, then **Next: Peaks →**
  (Manual) or **Analyze** (other modes).
- **③ Peaks:** the plot zoomed to the region (a little margin) with S1, S2,
  R1, R2 draggable and snapping as now, region locked. A hint line,
  **← Region**, **Analyze**.
- **④ Results:** the plot zoomed to the region with the markers shown but not
  draggable, the results list (with the periods above), a line
  `Saving as: <sample> · <date> <time> · <temperature> °C · <gas>   Edit`
  (Edit jumps to Setup), **Save to database** and its status, **← Back**.
- **Step bar:** a step can be clicked once reached. Changing a setting or the
  region after results clears the result (as now), so ④ greys out until the
  next Analyze.
- **Temperature:** the form shows the header's typed value at Setup. When an
  analysis finishes it becomes the measured average over the region, unless
  Omer typed in the field himself. This keeps "measured, else typed".
- **Opening a new run** from the Runs tab starts at ① Setup.
- **Unchanged:** the maths, what is saved, the duplicate check, the offline
  queue, the analysis subprocess.

## Left to the builder
Exact widget layout, how the save form is split into a form part (Setup) and
a Save part (Results), and the tests.
