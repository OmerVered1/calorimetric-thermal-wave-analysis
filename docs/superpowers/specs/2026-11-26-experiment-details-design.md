# Experiment details that travel with each run (short design)

**Date:** 2026-11-26 · **Approved by:** Omer (question tool, same day)

## Intent
When Omer creates an experiment he fills in the run details once (sample,
devices, temperature, gas, radii). Every run of that experiment carries them
into the Analysis tab, so they are not retyped at save time. Date and time
stay automatic (the run's start).

## Decisions (Omer's)
- Details live **on the experiment**: New asks for them; the experiment panel
  shows them with **Edit details…**; each run takes the values current at Start.
- **Temperature:** the measured average over the selected region when the run
  has a temperature column, otherwise the typed value.
- **Desktop only.** The webapp's upload is unchanged.
- Same fields as the Analysis save form plus inner and outer radius:
  Sample, Power source, Response device, Temperature (°C), Gas, r₁, r₂.

## Approaches considered
1. **Details on the experiment, written into the run CSV header at Start;
   Analysis reads the header** (chosen). The file is self-describing: editing,
   renaming or deleting the experiment later, or opening the file on another
   PC or from the NAS, still gives the right details.
2. Look the experiment up by name at analysis time. Rejected: breaks when the
   experiment changes after the run, or on another computer.
3. A sidecar details file next to each CSV. Rejected: it can get separated
   from the CSV (NAS copies, manual moves).

## Design
- **Experiment record:** a new `details` dict: `sample`, `power_source`,
  `response_device`, `temperature_c` (text, may be blank), `gas`, `r1_mm`,
  `r2_mm`. Old records have none: blank details.
- **New dialog:** name plus the details. Defaults: power source from the
  connected Keithley ("Keithley 2602B"), response device from the connected
  calorimeter, gas Ar, r₁ 6.72, r₂ 14.86, sample and temperature blank.
  Clone copies details.
- **Experiment panel:** details shown under the experiment name;
  **Edit details…** opens the same form and saves straight to the store.
- **Run header at Start:** `# Sample:`, `# PowerSource:`, `# ResponseDevice:`,
  `# Temperature:`, `# Gas:`, `# InnerRadius:`, `# OuterRadius:` (mm), written
  only for filled fields. One-word keys, because the header parser reads
  `# Word: value`.
- **Analysis:** `parse_run_header` returns the new keys. Opening a run sets
  r₁/r₂ in Analysis settings from the header. The save form fills Sample,
  Power source, Response device and Gas from the header (falling back to
  today's sources), and Temperature from the measured average, else the
  header. Everything stays editable.
- **Unchanged:** runs without details analyze exactly as today. The golden
  command-equivalence test is unaffected (no instrument commands change).

## Also in this change (separate request, same day)
Every grey text colour in the desktop app becomes black: labels, hints,
placeholders, status lines, table headers and plot labels. Disabled controls
stay grey (Omer's choice), so they still read as off.

## Left to the builder
Exact widget layout of the form and panel, and the tests.
