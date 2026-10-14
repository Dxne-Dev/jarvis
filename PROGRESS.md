# Avancement

## Phase en cours

**1 — Fondations.** Construite et vérifiée sur la machine ; reste la CI verte sur GitHub, le démarrage à froid et la PR `dev → main`.

## Fait

### Phase 0 — Démarrage (14/10/2026)
- Brief lu ; ancien Jarvis lu en entier dans `legacy/` (non versionné).
- Dépôt privé https://github.com/octavebahoun/O-jarvis, historique propre, hooks git locaux contre les fuites.
- Machine et clés vérifiées par de vrais appels (détail plus bas).

### Phase 1 — Fondations (14/10/2026)
- Moteur Python : API locale protégée par jeton, trousseau, bus d'événements, traces, logs filtrés, migrations, erreurs normalisées.
- App Tauri : lancement et arrêt du moteur, barre système, `Ctrl+Q`, une seule instance.
- Interface : tokens de design, sphère WebGL2 (6 états), écrans Accueil, Journal et traces, Réglages (clés, animations, qualité de la sphère).
- CI GitHub Actions écrite ; scripts `install-dev.sh` et `install-launcher.sh`.
- Docs : `docs/architecture.md`, `docs/journal/01-fondations.md`, `docs/checklist-manuelle.md`.

## Ensuite

1. CI entièrement verte (coque Rust en cours) puis PR `dev → main` de la phase 1.
2. Phase 2 — parler à Jarvis : routeur de modèles, conversation, mémoire, moteur de contexte, voix.

## Problèmes ouverts

- `OPENAI_API_KEY` et `ANTHROPIC_API_KEY` absentes : adaptateurs simulés (phase 2).
- Ollama pas encore installé (phase 2).
- Deux moteurs orphelins d'une ancienne tentative tournent encore (PID 53438 et 56076, ports 8765 et 40227) : sans effet, à arrêter avec `kill 53438 56076`.
- `braces` (outil de lint) a une faille « haute » sans correctif : accepté, voir `DECISIONS.md`.
- Un test WebSocket a échoué 2 fois sur une vingtaine de passes complètes, jamais seul. Cause probable corrigée (lecture de l'exception d'une tâche annulée) ; à surveiller.

## Vérifications

| Date | Vérification | Résultat |
|---|---|---|
| 14/10 | DeepSeek, OpenRouter, Cartesia, Tavily, GitHub, Notion, Telegram, Google | 10 clés OK par appel réel |
| 14/10 | Cartesia `sonic-3.6` en `fr` | WAV reçu, premier octet en 114 ms |
| 14/10 | Historique publié | Ni `.env`, ni `BRIEF.md`, ni mention interdite |
| 14/10 | Moteur : ruff, mypy strict, pytest | 0 erreur ; 155 tests ; couverture 93 % |
| 14/10 | Interface : tsc, ESLint, Stylelint, Prettier, Vitest | 0 erreur ; 34 tests |
| 14/10 | Coque : fmt, clippy `-D warnings`, cargo test | 0 erreur ; 5 tests |
| 14/10 | Bout en bout Playwright + vrai moteur + axe | 6/6 ; aucune violation sérieuse |
| 14/10 | Sphère dans l'app réelle (WebKitGTK) | 59,7 à 60,0 i/s, p95 ≤ 19 ms |
| 14/10 | `pip-audit` / `pnpm audit --prod` | aucune faille |
| 14/10 | Lanceur « un clic » (`gtk-launch o-jarvis`, binaire release) | app + moteur démarrés ; trousseau GNOME |
| 14/10 | Icône de la barre système (D-Bus StatusNotifier) | enregistrée, active, menu « Ouvrir » / « Quitter » |
| 14/10 | « Quitter » depuis la barre système | app et moteur arrêtés en ~1 s (`stdin_closed`, `engine_stopped`) |
| 14/10 | App tuée (SIGTERM) | le moteur s'arrête seul |
| 14/10 | Démarrage à froid (clone GitHub neuf + `install-dev.sh` + `pnpm tauri dev`) | moteur prêt, interface connectée |
| 14/10 | CI GitHub : moteur, interface, bout en bout | vertes |
