# Avancement

## Phase en cours

**0 — Démarrage.** Message de l'étape 0 envoyé le 14/10/2026 ; démarrage de la phase 1 à la réponse ou après 10 minutes.

## Fait

- Brief lu. Ancien Jarvis cloné dans `legacy/` (non versionné) et lu en entier : `phase1.md` à `phase4.md`, `architecture.md`, `docs/RESUME-SESSION.md`, journaux `docs/phase1` à `docs/phase3`.
- `.gitignore`, exclusions locales (`.git/info/exclude`), hooks git locaux contre les fuites de secrets.
- Identité git locale : Octave BAHOUN-HOUTOUKPE `<octavebahoun@gmail.com>`.
- Machine vérifiée (voir `DECISIONS.md`).
- Clés du `.env` vérifiées par de vrais appels (résultats ci-dessous).

## Ensuite

1. Dépôt GitHub privé `O-jarvis`, premier commit, branches `main` et `dev`.
2. Phase 1 — Fondations : Tauri, React, moteur Python en sidecar, tokens de design, sphère, Réglages et trousseau, bus d'événements, traces v1, CI.

## Problèmes ouverts

- `OPENAI_API_KEY` et `ANTHROPIC_API_KEY` absentes : adaptateurs simulés.
- Ollama n'est pas installé (installation en espace utilisateur prévue).
- `/tmp` presque plein (2,9 Go de cache laissé par un autre programme) : fichiers lourds dans `~/.cache/o-jarvis/tmp`.
- Un autre programme (un éditeur) a encore un processus ouvert dans le dossier du projet : risque d'écritures concurrentes.

## Vérifications

| Date | Vérification | Résultat |
|---|---|---|
| 14/10 | DeepSeek `/models` + solde | OK — `deepseek-flash`, `deepseek-v4-pro`, solde disponible |
| 14/10 | OpenRouter `/key` | OK — offre gratuite, modèles `:free` uniquement |
| 14/10 | Cartesia `sonic-3.6` en `fr` | OK — 20 voix françaises, WAV reçu, premier octet en 114 ms |
| 14/10 | Tavily `/usage` | OK — plan Researcher, 0 / 1000 |
| 14/10 | GitHub `/user` | OK — jeton fine-grained, compte `octavebahoun` |
| 14/10 | Notion `/users/me` + `/search` | OK — intégration `o-jarvis`, pages partagées |
| 14/10 | Telegram `getMe` | OK — bot `@ojarvi_bot`, pas de webhook |
| 14/10 | Google OAuth loopback | OK — client « Desktop app » accepté, identifiants valides |
| 14/10 | Paquets système | Tauri, WebKitWebDriver, PortAudio, Xvfb, portails : présents |
