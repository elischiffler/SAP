#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ "$(uname -s)" != Darwin ] || ! command -v xcrun >/dev/null; then
    echo 'The SAP Bluetooth probe requires macOS and the Xcode command-line tools.' >&2
    exit 1
fi
source_dir=bridges/macos
app_dir="$HOME/Library/Caches/local.sap.bluetooth-probe/SAP Bluetooth Probe.app"
plist="$app_dir/Contents/Info.plist"
executable="$app_dir/Contents/MacOS/SAPBluetoothProbe"
rebuild=false
if ! codesign --verify --strict "$app_dir" >/dev/null 2>&1; then
    rebuild=true
fi
for source in "$source_dir"/*.swift "$source_dir/Info.plist"; do
    if [ ! -x "$executable" ] || [ "$source" -nt "$executable" ]; then
        rebuild=true
    fi
done
if [ "$rebuild" = true ]; then
    mkdir -p "$app_dir/Contents/MacOS"
    cp "$source_dir/Info.plist" "$plist"
    xcrun --sdk macosx swiftc -swift-version 6 -warnings-as-errors "$source_dir"/*.swift -o "$executable"
    xattr -dr com.apple.FinderInfo "$app_dir" 2>/dev/null || true
    xattr -dr com.apple.ResourceFork "$app_dir" 2>/dev/null || true
    codesign --force --sign - "$app_dir" >/dev/null
fi
exec "$executable" "$@"
