# O-jarvis

Assistant personnel desktop pour Ubuntu. On lui parle à voix haute (« Hey Jarvis »), il se souvient, agit sous contrôle et sait s'étendre.

![Accueil d'O-jarvis : la sphère au centre](docs/captures/accueil.webp)

- **App** : Tauri v2 (Rust) + React + TypeScript.
- **Cerveau** : moteur Python (FastAPI) lancé par l'app, sur `127.0.0.1` uniquement, protégé par un jeton tiré à chaque lancement.
- **Données** : SQLite local ; les clés vivent dans le trousseau du système.

Le projet est en construction, phase par phase. L'état du travail est dans [`PROGRESS.md`](./PROGRESS.md), les choix dans [`DECISIONS.md`](./DECISIONS.md), le journal dans [`docs/journal/`](./docs/journal/README.md), le schéma dans [`docs/architecture.md`](./docs/architecture.md).

## Installer pour le développement

Ubuntu 24.04 ou plus récent, Node.js 22+. Le script n'utilise pas sudo : s'il manque des paquets système, il affiche la commande `apt` à lancer.

```bash
git clone https://github.com/octavebahoun/O-jarvis.git
cd O-jarvis
scripts/install-dev.sh
```

Complète ensuite `.env` avec tes clés (voir `.env.example`). Au premier lancement, l'app les importe dans le trousseau.

## Lancer

```bash
cd app && pnpm tauri dev          # développement, rechargement à chaud
scripts/install-launcher.sh       # compile et ajoute « O-jarvis » au menu des applications
```

Fermer la fenêtre arrête tout, moteur compris. `Ctrl+Q` aussi.

## Vérifier

```bash
cd engine && uv run pytest -m "not real"     # moteur
cd app && pnpm test && pnpm e2e               # interface, puis bout en bout avec le vrai moteur
cd app/src-tauri && cargo test                # coque
```
