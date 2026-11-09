#!/bin/zsh
# Builds a self-contained Thermal Printer.app (with its own Python) into dist/,
# plus a zip to copy to other Macs. Pass --install to also put it in ~/Applications.
set -e
cd "${0:A:h}/.."

PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-aarch64-apple-darwin-install_only_stripped.tar.gz"
dist="dist"
app="$dist/Thermal Printer.app"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

echo "Downloading Python…"
curl -fsSL "$PYTHON_URL" | tar -xz -C "$work"
python="$work/python/bin/python3"
"$python" -m pip install -q --disable-pip-version-check --no-warn-script-location pillow pyusb libusb-package

echo "Drawing the icon…"
"$python" mac/icon.py "$work/icon.png"
mkdir "$work/AppIcon.iconset"
for size in 16 32 128 256 512; do
  sips -z $size $size "$work/icon.png" --out "$work/AppIcon.iconset/icon_${size}x${size}.png" > /dev/null
  double=$((size * 2))
  sips -z $double $double "$work/icon.png" --out "$work/AppIcon.iconset/icon_${size}x${size}@2x.png" > /dev/null
done
iconutil -c icns "$work/AppIcon.iconset" -o "$work/AppIcon.icns"

echo "Building the app…"
bundle="$work/bundle"
mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources/app"
swiftc -O -swift-version 5 -framework Cocoa -framework WebKit mac/main.swift -o "$bundle/Contents/MacOS/Thermal Printer"
cp "$work/AppIcon.icns" "$bundle/Contents/Resources/"
cp -R thermal.py document.py server.py index.html fonts "$bundle/Contents/Resources/app/"
mv "$work/python" "$bundle/Contents/Resources/python"
cat > "$bundle/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Thermal Printer</string>
  <key>CFBundleDisplayName</key><string>Thermal Printer</string>
  <key>CFBundleExecutable</key><string>Thermal Printer</string>
  <key>CFBundleIdentifier</key><string>com.lucabradfield.thermalprinter</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST
codesign --force --deep --sign - "$bundle" 2> /dev/null

rm -rf "$app" "$dist/Thermal-Printer-mac.zip"
mkdir -p "$dist"
cp -R "$bundle" "$app"
ditto -c -k --keepParent "$app" "$dist/Thermal-Printer-mac.zip"
echo "Built $app"

if [[ "$1" == "--install" ]]; then
  rm -rf "$HOME/Applications/Thermal Printer.app"
  mkdir -p "$HOME/Applications"
  cp -R "$app" "$HOME/Applications/"
  echo "Installed to ~/Applications"
fi
