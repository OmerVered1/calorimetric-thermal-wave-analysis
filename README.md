# Calorimetric Thermal Wave Analysis Program

Drives a Keithley SMU as the heater source for radial Ångström thermal-wave
measurements in a Calvet calorimeter, and records the calorimeter alongside it.

> **Status: 1.0.0 in development.** Forked from
> [keithley-smu-control](https://github.com/OmerVered1/keithley-smu-control) v3.6.0,
> which stays installed and in use until this program has been proven against
> real hardware. The two install side by side and keep separate settings; saved
> calorimeter profiles and setups from the old program are carried over
> automatically, and the old program's files are never written.

---

One program for the Keithley 2450, 6430, 2602B and 2611A. There is no
launcher: the window opens, and you choose the source meter model when you
connect. Controls that only some models have (the 2450's front/rear terminals,
the 6430's guard and high-capacitance modes, the 2602B's second channel) appear
only when that model is connected.

## Supported Instruments

### Keithley 2450 SourceMeter
- USB VISA communication (pyvisa)
- Source voltage/current: +/-200V, +/-1A
- Front/rear terminal selection

### Keithley 6430 Sub-Femtoamp Remote SourceMeter
- RS-232 serial communication (pyserial) via USB-to-serial converter
- Source voltage/current: +/-105V, +/-105mA
- Sub-femtoamp current measurement (down to 0.4 fA)
- Guard mode for ultra-low current

### Keithley 2602B Dual-Channel SourceMeter
- VISA communication (USB, GPIB, Ethernet, RS-232 via pyvisa)
- Dual independent channels (smua/smub)
- Source voltage/current: +/-40V, +/-3A DC (10A pulse), 40.4W per channel
- TSP (Test Script Processor) native command interface
- Channel A/B toggle with independent output controls

### Keithley 2611A SourceMeter
- LAN (LXI Class C / VXI-11), USB, GPIB, RS-232
- Source voltage/current: +/-200V, +/-1.5A
- Single channel (smua), TSP native command interface
- Same TSP command family as the 2602B

## Features (All Instruments)

- Live multimeter mode with large digital displays
- I-V sweep characterization (Linear, List, Log)
- Dual Y-axis graphing with presets
- Wave generator tool for custom waveforms
- Real Time tab: SMU and calorimeter signals on one time axis
- Calorimeter panel (Setaram C80 / Drop): direct connect, or sniff mode
  alongside Calisto — see [Calorimeter setups](#calorimeter-setups)
- CSV export with auto-save
- Configuration save/load (JSON)
- Safety limits enforcement, with each model's own hardware maxima
- Simulation mode for testing without hardware

The Real Time tab and the calorimeter panel were 2602B/2611A-only in
keithley-smu-control; the 2450 and 6430 have them here for the first time.

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Choose **Simulate** in the connect dialog to try any model without
hardware.

### Tests

```bash
QT_QPA_PLATFORM=offscreen pytest tests/
```

`tests/golden/` holds the exact instrument command sequences the four original
per-model programs sent for a set of scenarios; the merged window is tested
against them, so a change that alters what reaches an instrument fails here.

### Building

```bash
pyinstaller keithley_suite.spec --noconfirm
```

Pushing a `v*` tag builds the Windows installer and macOS app on GitHub Actions
and attaches them to a release, which the in-app updater picks up.

## File Structure

```
main.py                      # Start here

ctwa/
  app.py                     # The main window (was four per-model programs)
  connect_panel.py           # Connect dialog: model, transport, address
  theme.py                   # Palette, stylesheet and plot styling in one place
  assets/                    # Stylesheet icons (check mark, chevrons)
  instruments/
    capabilities.py          # What each model has: channels, ranges, limits, extras
    registry.py              # Model list and how each one connects
    smu.py                   # One interface over the four drivers
    discovery.py             # VISA / serial scans, run off the UI thread

keithley2450_driver.py       # K2450 VISA driver
keithley6430_driver.py       # K6430 RS-232 serial driver
keithley2602b_driver.py      # K2602B TSP driver (dual-channel)
keithley2611a_driver.py      # K2611A TSP driver (single-channel, LAN/GPIB/USB/RS-232)
network_setup.py             # Reaching a LAN instrument on another subnet (Windows)

realtime_tab.py              # Real Time tab
calorimeter_reader.py        # Setaram calorimeter LAN reader (the "Calorimeter" panel)
sniffer/                     # Passive packet capture/decode, vendored from lan-signal-sniffer —
                             # backs the calorimeter panel's "Sniff mode" (watch Calisto's own
                             # traffic instead of connecting, so both can run at once)
calorimeter_profiles/        # Traffic-decoding profiles for the C80 / Drop (bundled defaults;
                             # a user-saved profile of the same name replaces one)
calorimeter_setups.py        # Named setups: instrument + IP + capture adapter + which profile
calorimeter_discovery.py     # Derives signals from a live capture (no Qt — testable headless)
calorimeter_wizard.py        # "New setup…" dialog: capture, pick fields, name them, save
signal_units.py              # Unit menus and plot colors for run-time-defined signals
sniff_diagnose.py            # Standalone per-layer capture diagnostic (run as admin)

updater.py, _version.py      # In-app updates from this repo's GitHub releases
keithley_suite.spec          # PyInstaller build
windows_installer.iss        # Inno Setup installer
requirements.txt             # All dependencies
tests/                       # pytest suite
```

## Calorimeter setups

Sniff mode decodes an instrument's traffic using a *profile* that says which
request bytes carry which measurement. The bundled profiles cover the C80 and
Drop as they behaved when captured; if an instrument answers differently, the
status bar reports packets captured but nothing decoded.

**Setup ▸ New…** in the Calorimeter panel fixes that without a code change. It
captures for a few seconds, lists every request the vendor software sends, and
for each one shows the byte field that most looks like a measurement, with its
recent values. Name the ones you recognise, give them units, and save. The
signals become a profile in your application-data folder — which shadows the
bundled one of the same name, and survives app updates — and the setup itself
remembers the IP, the capture adapter and which profile to use, so reconnecting
is one dropdown.

Signals defined this way flow through to the Real Time plot (with their own
axes, colors and unit menus) and to the merged sweep CSV columns.

Setups configure **passive watching only**. Direct connect still uses the
built-in command list, so the app can never transmit bytes typed into a dialog
to an instrument that may be mid-run under Calisto.

## Author

**Omer Vered**

## Disclaimer

This project is an independent, open-source tool developed by a third party. It is **not affiliated with, endorsed by, or supported by Tektronix, Inc. or Keithley Instruments**. "Keithley" and "SourceMeter" are registered trademarks of Tektronix, Inc. These names are used solely for the purpose of identifying the instruments this software is designed to communicate with.

Communication with instruments is performed using standard SCPI commands and TSP (Test Script Processor) as documented in the publicly available Keithley reference manuals. No proprietary Keithley/Tektronix software or source code was used or reproduced.

**Use at your own risk.** This software controls physical instruments capable of sourcing potentially hazardous voltages and currents. The author accepts no responsibility for damage to instruments, equipment, or any other harm resulting from the use or misuse of this software. Always verify safety limits and operating parameters before use. It is the user's sole responsibility to ensure safe and correct operation in accordance with the instrument's official documentation.

## License

MIT License — see [LICENSE](LICENSE) for full text.

Copyright (c) 2026 Omer Vered
