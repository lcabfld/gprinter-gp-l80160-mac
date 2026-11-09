# Gprinter GP-L80160 for Mac

A Mac app and driver for the **Gprinter GP-L80160** thermal receipt printer. Print photos, SVGs and Markdown over USB, with no official Mac driver needed.

Drop or paste files in, tune photos with live-preview sliders, and print. Everything runs locally.

## The printer

| | |
|---|---|
| Model | Gprinter (Gainscha) GP-L80160 |
| Shows up as | "USB Portable Printer" by STMicroelectronics, USB ID `0416:5011`, printer class |
| Bluetooth name | `BlueToothPrinter`, as a serial port at `/dev/cu.BlueToothPrinter` |
| Command language | ESC/POS (raster images via `GS v 0`) |
| Printable width | 384 dots, 48 mm, at 8 dots per mm, even on 80 mm paper |

Other ESC/POS printers with a 384-dot head and USB ID `0416:5011` may work too, but this is only tested on the GP-L80160.

## Install

1. Download `Thermal-Printer-mac.zip` from the [latest release](../../releases/latest) and unzip it.
2. Move **Thermal Printer** into Applications.
3. The first time, right-click it and choose **Open**. It isn't signed by an Apple developer, so macOS asks once. On newer macOS versions, you may need **System Settings › Privacy & Security › Open Anyway** instead.

Requires an Apple Silicon Mac (M1 or later) on macOS 13 or newer. Python is bundled, so nothing else needs installing.

## Use

- **Upload:** drop files anywhere in the window, click to browse, or paste with ⌘V. Photos (JPG, PNG, WebP), SVGs, Markdown and plain text all work.
- **Auto Print:** when on, files print as soon as they're added. When off, they wait in the queue as Ready until you click **Print** or **Print All**.
- **Markdown:** type or paste into the Markdown box. Headings, bold, italics, lists, quotes, code and dividers print in Geist.
- **Adjustments:** exposure, contrast, gamma, levels clip and row delay for photos, with a dot-accurate preview and **Reprint Photo**. Turn on **Print Settings Under Photo** to label each print with the values used.

Settings are saved in `~/Library/Application Support/Thermal Printer/`.

## What we learned about the GP-L80160

- **Width:** the print head is 384 dots (48 mm) wide, even though the paper is wider. Anything past 384 dots is silently cut off the right side, so everything is scaled to that width.
- **USB stalls:** the printer's USB bulk endpoint stalls (`Pipe error`) every few hundred bytes, at random points. Clearing the stall mid-image drops or repeats data and turns the rest of the print into garbage text. So each row is sent as its own `GS v 0` command in a single 64-byte USB packet. A stall then costs at most one row, and the driver reconnects and resends that packet.
- **Darkness:** slower printing lets the head cool between rows and comes out lighter. 10 ms per row gives the darkest blacks. A warm head, from printing several jobs in a row, also prints darker.
- **Bluetooth:** it works for text, but the printer seems to accept only one Bluetooth connection per power cycle, and a stuck connection can block the Mac's serial port until a restart. USB is more reliable.
- **Status:** the printer doesn't answer status queries (`DLE EOT`) over USB, only over Bluetooth.
- **Heat commands:** `ESC 7` isn't supported and prints as garbage. There's no known working darkness command.
- **macOS printing:** macOS no longer allows raw printer queues, and the CUPS USB backend fails on this printer's stalls, so the app talks to it directly through libusb.
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
