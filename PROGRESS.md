# Avancement

## Phase en cours

**2 — Parler à Jarvis.** Terminée : les deux critères de sortie passent (réponse parlée en 1,75 s de médiane avec DeepSeek ; fait rappelé d'une session à l'autre), la boucle de vérification aussi. PR `dev → main` ouverte. Prochaine : phase 3.

## Fait

### Phase 0 — Démarrage (14/10/2026)
- Brief lu ; ancien Jarvis lu en entier dans `legacy/` (non versionné).
- Dépôt privé https://github.com/octavebahoun/O-jarvis, historique propre, hooks git locaux contre les fuites.
- Machine et clés vérifiées par de vrais appels.

### Phase 1 — Fondations (14/10/2026)
- Moteur Python : API locale protégée par jeton, trousseau, bus d'événements, traces, logs filtrés, migrations, erreurs normalisées.
- App Tauri : lancement et arrêt du moteur, barre système, `Ctrl+Q`, une seule instance.
- Interface : tokens de design, sphère WebGL2 (6 états), Accueil, Journal et traces, Réglages.
- CI GitHub Actions ; scripts `install-dev.sh` et `install-launcher.sh`. PR #1 ouverte.

### Phase 2 — Parler à Jarvis (15/10/2026)
- Routeur de modèles : DeepSeek, OpenRouter, OpenAI, Anthropic, Ollama, modèle de test ; politique par tâche, disjoncteur, bascule signalée, modèle imposé depuis Réglages, délai maximal avant le premier mot, modèle local préchargé en cas de panne.
- Conversation en flux (SSE), markdown, historique cherchable, renommer, supprimer.
- Mémoire (faits, préférences, profil) visible et modifiable ; embeddings e5 locaux, sqlite-vec et FTS5 ; extraction automatique désactivable.
- Moteur de contexte : budget de jetons, sélection visible dans la trace.
- Voix : openWakeWord + vérification locale, Silero VAD, Whisper base (fenêtre courte), Cartesia en flux, Piper en repli, annulation d'écho PipeWire, interruption, relance sans mot de réveil, sous-titres.
- Bureau : raccourci global Ctrl+Alt+J (portail GlobalShortcuts), notifications.
- Écrans : Accueil (sphère + conversation + voix), Historique, Mémoire, Réglages (modèles, voix).
- Docs : `docs/journal/02-parler-a-jarvis.md`, décisions, checklist manuelle.

## Ensuite

1. Phase 3 — Jarvis agit : outils à schémas stricts, niveaux de permission, journal immuable, planificateur et exécuteur, recherche web, fichiers, sandbox, navigateur autonome, découverte des capacités.

## Problèmes ouverts

- Deux moteurs orphelins d'une ancienne tentative tournent encore (PID 53438 et 56076, ports 8765 et 40227) : sans effet, à arrêter avec `kill 53438 56076`.
- `braces` (outil de lint) a une faille « haute » sans correctif : accepté, voir `DECISIONS.md`.
- Mot de réveil prononcé avec l'accent français d'espeak-ng : non détecté (0/4) ; les voix naturelles le sont. À confirmer au vrai micro (checklist).
- OpenRouter gratuit renvoie souvent 429 : il ne sert que de second repli.

## Vérifications

| Date | Vérification | Résultat |
|---|---|---|
| 14/10 | DeepSeek, OpenRouter, Cartesia, Tavily, GitHub, Notion, Telegram, Google | 10 clés OK par appel réel |
| 14/10 | Cartesia `sonic-3.6` en `fr` | WAV reçu, premier octet en 114 ms |
| 14/10 | Historique publié | Ni `.env`, ni `BRIEF.md`, ni mention interdite |
| 14/10 | Sphère dans l'app réelle (WebKitGTK) | 59,7 à 60,0 i/s, p95 ≤ 19 ms |
| 14/10 | Lanceur « un clic », barre système, « Quitter », app tuée | app et moteur démarrent et s'arrêtent ensemble |
| 14/10 | Démarrage à froid (clone neuf + `install-dev.sh` + `pnpm tauri dev`) | moteur prêt, interface connectée |
| 15/10 | Fait rappelé d'une session à l'autre (vrai DeepSeek) | 3 faits extraits ; « Thé à la menthe », « Tu habites à Cotonou » |
| 15/10 | Corpus vocal (36 fichiers : Piper, espeak-ng, Cartesia) | réveil 17/21, 0 faux réveil ; 6/6 accent français Cartesia (3 par vérification) |
| 15/10 | Latence fin de phrase → premier son, vrai pipeline, DeepSeek + Cartesia | médiane 1,75 s, max 1,9 s (17 tours) |
| 15/10 | Transcription Whisper base, fenêtre courte | 0,45 s (contre 1,7 s) ; `small` : 5 s, écarté |
| 15/10 | Essai au vrai micro (Octave) | réveil OK ; transcription locale illisible (micro à 25 %, Whisper base) |
| 15/10 | Transcription Cartesia Ink-2 contre Whisper base, corpus dégradé (−30 dB + souffle) | 0 % contre 93 % de mots faux ; texte 180 ms après la phrase |
| 15/10 | Vrai pipeline avec Ink-2 + DeepSeek + Cartesia | 12/12 tours, 0 % d'erreurs, latence médiane 1,72 s |
| 15/10 | Voix sur la machine réelle (micro, annulation d'écho) | prête en 6 s ; 50 trames en 4 s ; arrêt en 1,1 s, module retiré |
| 15/10 | Moteur : ruff, mypy strict (code + tests), pytest | 0 erreur ; 346 tests ; couverture 91 % |
| 15/10 | Interface : tsc, ESLint, Stylelint, Prettier, Vitest | 0 erreur ; 36 tests |
| 15/10 | Coque : fmt, clippy `-D warnings`, cargo test | 0 erreur |
| 15/10 | Bout en bout Playwright + vrai moteur + axe | 11/11, dont un tour vocal (audio simulé) ; aucune violation sérieuse |
| 15/10 | `pip-audit` / `pnpm audit --prod` / `cargo audit` | aucune faille ; 2 avertissements GTK acceptés (voir DECISIONS) |
| 15/10 | Démarrage à froid (clone neuf de `dev`, `install-dev.sh`, dossier vierge) | moteur prêt en 7,8 s ; voix prête en 35 s avec téléchargement et vérification des modèles (350 Mo) ; arrêt en 1,1 s |
| 15/10 | Revue de sécurité (section 7) | clé collée dans le chat envoyée au modèle et stockée en clair : corrigé (masquage central) ; noms de périphériques passés à `pactl` : validés |
| 15/10 | CI GitHub : moteur, interface, bout en bout, coque | vertes |
