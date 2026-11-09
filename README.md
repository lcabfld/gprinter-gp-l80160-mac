# Thermal Printer

A Mac app for printing photos, SVGs and Markdown on a Gprinter GP-L80160 (or similar ESC/POS thermal printer) over USB.

Drop or paste files in, tune photos with live-preview sliders, and print. Everything runs locally.

## Install

1. Download `Thermal-Printer-mac.zip` from the latest release and unzip it.
2. Move **Thermal Printer** into Applications.
3. The first time, right-click it and choose **Open**. It isn't signed by an Apple developer, so macOS asks once. On newer macOS versions, you may need **System Settings › Privacy & Security › Open Anyway** instead.

Requires an Apple Silicon Mac (M1 or later) on macOS 13 or newer. Python is bundled, so nothing else needs installing.

## Use

- **Upload:** drop files anywhere in the window, click to browse, or paste with ⌘V. Photos (JPG, PNG, WebP), SVGs, Markdown and plain text all work.
- **Auto Print:** when on, files print as soon as they're added. When off, they wait in the queue as Ready until you click **Print** or **Print All**.
- **Markdown:** type or paste into the Markdown box. Headings, bold, italics, lists, quotes, code and dividers print in Geist.
- **Adjustments:** exposure, contrast, gamma, levels clip and row delay for photos, with a dot-accurate preview and **Reprint Photo**. Turn on **Print Settings Under Photo** to label each print with the values used.

Settings are saved in `~/Library/Application Support/Thermal Printer/`.

## Printer notes

- The print head is 384 dots (48 mm) wide, so everything is scaled to that width.
- Prints use one self-contained USB packet per row. The printer's USB link stalls often, and this way a stall costs at most one row instead of corrupting the rest of the print.
- Slower row delays let the head cool and print lighter. 10 ms gives the darkest blacks.
- Text always prints at 10 ms per row.

## Build from source

Needs Xcode command line tools (`xcode-select --install`).

```bash
mac/build.sh            # builds dist/Thermal Printer.app and dist/Thermal-Printer-mac.zip
mac/build.sh --install  # also installs it to ~/Applications
```

The build downloads a standalone Python from [python-build-standalone](https://github.com/astral-sh/python-build-standalone) and bundles it with Pillow, PyUSB and libusb.

For development without building the app:

```bash
python3 -m venv .venv && .venv/bin/pip install pillow pyusb libusb-package
.venv/bin/python server.py            # opens http://localhost:8765
.venv/bin/python server.py --dry-run  # without a printer
.venv/bin/python thermal.py image photo.jpg
```

## Files

| File | Does |
|---|---|
| `thermal.py` | ESC/POS driver over USB (and Bluetooth serial), photo processing, command-line printing |
| `document.py` | Renders Markdown and SVG to print-ready images |
| `server.py` | Local web server and print queue behind the app |
| `index.html` | The app's interface |
| `mac/main.swift` | Native Mac window that runs the server |
| `mac/build.sh` | Builds the self-contained app |
| `mac/icon.py` | Draws the app icon |
| `fonts/` | Geist and Geist Mono, under the SIL Open Font License |
