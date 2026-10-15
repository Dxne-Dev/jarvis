# O-jarvis

Assistant personnel desktop pour Ubuntu. On lui parle à voix haute (« Hey Jarvis »), il se souvient, agit sous contrôle et sait s'étendre.

![Accueil d'O-jarvis : la sphère au centre](docs/captures/accueil.webp)

- **App** : Tauri v2 (Rust) + React + TypeScript.
- **Cerveau** : moteur Python (FastAPI) lancé par l'app, sur `127.0.0.1` uniquement, protégé par un jeton tiré à chaque lancement.
- **Voix** : « Hey Jarvis » reconnu en local, transcription Groq (français imposé, Whisper local en secours), voix Cartesia ou Piper ; réponse parlée en moins de 2 s ; on peut l'interrompre en parlant. Raccourci global : `Ctrl+Alt+J`.
- **Mémoire** : ce que Jarvis sait de toi est visible, modifiable et supprimable.
- **Actions** : il cherche sur le web, lit pages et fichiers, lance du code en bac à sable et pilote son propre navigateur. Toute action (cliquer, écrire, utiliser ta session) passe par un plan que tu valides ; chaque action est écrite dans un journal impossible à effacer. Détails : [`docs/securite.md`](./docs/securite.md).
- **Organisation** : rappels et tâches à l'heure dite ou sur un événement, qui survivent à un redémarrage ; briefing du matin ; GitHub, Notion et Google Agenda par leurs serveurs MCP officiels ; Telegram pour lui parler depuis ton téléphone.
- **Contrôle du PC** (désactivé par défaut, à activer dans Réglages) : ouvrir et fermer tes applications, ranger tes fichiers, « regarde mon écran » (lu sur ta machine par défaut, ou en ligne si tu le choisis).
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

Au premier lancement, le moteur télécharge ses modèles locaux (environ 350 Mo : recherche par le sens, mot de réveil, transcription, voix de secours), puis la voix est prête. Le script d'installation installe aussi le Chromium du navigateur de Jarvis (environ 170 Mo) et l'image Docker du bac à sable. Au premier lancement par l'icône, GNOME demande d'autoriser le raccourci `Ctrl+Alt+J`.

## Vérifier

```bash
cd engine && uv run pytest -m "not real"     # moteur
cd app && pnpm test && pnpm e2e               # interface, puis bout en bout avec le vrai moteur
cd app/src-tauri && cargo test                # coque
cd engine && uv run python tools/voice_bench.py --only cartesia   # voix : réveil et latence réels
```
