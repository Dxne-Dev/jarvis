#!/usr/bin/env bash
# Installe l'environnement de développement d'O-jarvis, sans sudo.
# Les paquets système manquants sont listés en une seule commande à lancer soi-même.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
have() { command -v "$1" >/dev/null 2>&1; }
step() { printf '\n==> %s\n' "$1"; }

step "Paquets système"
PACKAGES=(
  build-essential pkg-config curl file libssl-dev
  libwebkit2gtk-4.1-dev libjavascriptcoregtk-4.1-dev libsoup-3.0-dev libgtk-3-dev
  libayatana-appindicator3-dev librsvg2-dev libxdo-dev webkitgtk-webdriver xvfb
  libportaudio2 ffmpeg espeak-ng pulseaudio-utils xdotool wmctrl sqlite3 bubblewrap
)
missing=()
for pkg in "${PACKAGES[@]}"; do
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || missing+=("$pkg")
done
if ((${#missing[@]})); then
  echo "Il manque des paquets. Lance cette commande, puis relance ce script :"
  echo "  sudo apt install -y ${missing[*]}"
  exit 1
fi
echo "OK"

step "Outils en espace utilisateur"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
have uv || curl -LsSf https://astral.sh/uv/install.sh | sh
have cargo || curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
if ! have node; then
  echo "Node.js 22 ou plus est requis (nvm conseillé : https://github.com/nvm-sh/nvm)."
  exit 1
fi
have pnpm || npm install -g pnpm@10
echo "uv $(uv --version | cut -d' ' -f2) · cargo $(cargo --version | cut -d' ' -f2) · node $(node --version) · pnpm $(pnpm --version)"

step "Moteur Python"
(cd "$ROOT/engine" && uv sync --frozen)

step "Navigateur de Jarvis et bac à sable"
# Chromium piloté par le moteur (profil à part, jamais ton navigateur).
(cd "$ROOT/engine" && uv run playwright install chromium)
# Image du bac à sable pour le code (si Docker est là ; sinon bubblewrap prend le relais).
if have docker && docker info >/dev/null 2>&1; then
  docker pull --quiet python:3.12-alpine >/dev/null && echo "Bac à sable Docker prêt."
  # Serveurs MCP officiels (GitHub, Notion) : versions épinglées dans integrations/manager.py.
  docker pull --quiet ghcr.io/github/github-mcp-server:v1.12.2 >/dev/null &&
    docker pull --quiet node:24.21.0-alpine3.24 >/dev/null &&
    echo "Images des intégrations GitHub et Notion prêtes."
else
  echo "Docker absent ou arrêté : le code tournera sous bubblewrap (bwrap)."
fi

step "Interface"
(cd "$ROOT/app" && pnpm install --frozen-lockfile)

step "Fichier .env"
if [[ -f "$ROOT/.env" ]]; then
  echo ".env présent (ses clés seront importées dans le trousseau au premier lancement)."
else
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo ".env créé depuis .env.example : complète les clés que tu as."
fi

step "Terminé"
echo "Lancer en développement : cd app && pnpm tauri dev"
echo "Créer le lanceur « un clic » : scripts/install-launcher.sh"
