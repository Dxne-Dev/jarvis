#!/usr/bin/env bash
# Compile l'app et crée un lanceur dans le menu des applications (un clic pour tout démarrer).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/app/src-tauri/target/release/o-jarvis"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/128x128/apps"

if [[ "${1:-}" != "--sans-compilation" ]]; then
  (cd "$ROOT/app" && pnpm tauri build --no-bundle)
fi
[[ -x "$BIN" ]] || { echo "Binaire introuvable : $BIN"; exit 1; }

# Le nom du fichier .desktop est l'identifiant de l'app : le portail du bureau s'en sert
# pour reconnaître O-jarvis (raccourci clavier global, notifications).
APP_ID="io.github.octavebahoun.ojarvis"

mkdir -p "$APPS" "$ICONS"
cp "$ROOT/app/src-tauri/icons/128x128.png" "$ICONS/o-jarvis.png"
# Ancien nom du lanceur (avant le raccourci global) : remplacé par le nouveau.
rm -f "$APPS/o-jarvis.desktop"
cat > "$APPS/$APP_ID.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=O-jarvis
Comment=Assistant personnel
Exec=$BIN
Icon=o-jarvis
Terminal=false
Categories=Utility;
StartupWMClass=o-jarvis
DESKTOP
update-desktop-database "$APPS" 2>/dev/null || true
echo "Lanceur installé : cherche « O-jarvis » dans le menu des applications."
