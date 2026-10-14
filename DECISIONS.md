# Décisions

Chaque choix technique ou produit, avec sa raison. Le brief gagne sur l'ancien repo.
Format : **choix** — raison. Date entre parenthèses quand c'est utile.

## Dépôt et traçabilité

- **Historique neuf (14/10/2026)** — l'ancien dépôt GitHub a été supprimé et les deux commits locaux ne respectaient pas les règles de traçabilité du projet. Le nouvel historique part d'une racine propre. Les anciens commits restent en local sur des branches `archive-v0-*`, jamais poussées (un hook `pre-push` le garantit), avec une sauvegarde `git bundle` dans `~/.cache/o-jarvis/`.
- **Hooks git locaux** (`.git/hooks`, non versionnés) — ils refusent un commit qui contient une valeur du `.env`, un motif de clé connu, un fichier interdit ou une mention interdite par les règles de traçabilité. Le `.env` contient aussi des clés d'autres projets : le risque de fuite est réel.
- **Branches** — travail sur `dev`, PR `dev → main` à la fin de chaque phase. Octave merge.

## Machine (vérifiée le 14/10/2026)

- **Ubuntu 26.04.1 LTS, GNOME 50, Wayland uniquement** — GNOME 50 n'a plus de session X11. Le chemin X11 du code se teste sous Xvfb.
- **i5-4200M (2 cœurs, 4 threads, AVX2), 7,2 Go de RAM, Intel HD 4600 (pas de VRAM dédiée)** — machine modeste : tout ce qui tourne en local doit rester léger (pas de PyTorch, modèles quantifiés, chargement à la demande).
- **Docker 29.1.3, utilisateur dans le groupe `docker`** — sandbox de code avec Docker ; bubblewrap en repli.
- **Fuseau `Europe/Paris`** — stockage en UTC, affichage et planification dans le fuseau du système.
- **`/tmp` est un tmpfs plein à 81 %** (cache laissé par un autre programme) — fichiers temporaires lourds dans `~/.cache/o-jarvis/tmp`.

## Architecture

- **Deux processus : app Tauri v2 (Rust + React/TypeScript/Vite) et moteur Python (FastAPI)** — imposé par le brief. Pas de microservices.
- **Le moteur écoute `127.0.0.1` sur un port libre choisi par lui-même** — il annonce son port sur sa sortie standard ; aucune course sur un port fixe.
- **Jeton aléatoire par lancement, transmis par l'entrée standard** — invisible dans `/proc/<pid>/environ`. Le moteur s'arrête quand l'entrée standard se ferme : si l'app meurt, il meurt aussi.
- **Monorepo** : `app/` (Tauri + React), `engine/` (Python), `docs/`, `scripts/`.
- **Identifiants de code en anglais, interface, docs et commits en français** — convention lisible par tous les outils, produit en français.
- **Le moteur se lance depuis l'environnement Python du dépôt** (`engine/.venv`) en développement et pour le lanceur « un clic » ; un moteur empaqueté (PyInstaller) prendra la priorité en phase 7. Ordre de recherche : empaqueté, `OJARVIS_ENGINE_DIR`, sources.
- **WebSocket authentifiée par son premier message** — un navigateur ne peut pas poser d'en-tête sur une WebSocket ; l'origine est aussi vérifiée.
- **Fermer la fenêtre arrête tout** (le brief) ; la barre système offre « Ouvrir » et « Quitter » ; `Ctrl+Q` quitte.

## Moteur Python

- **Python 3.12 géré par uv** — faster-whisper et onnxruntime ne sont pas fiables sur le Python 3.14 du système.
- **Qualité** : ruff (lint + format), mypy strict, pytest, couverture ≥ 80 % sur le métier.
- **SQLite unique (mode WAL) avec SQLAlchemy 2 et Alembic** — un seul fichier pour le relationnel, les vecteurs et le graphe. Migrations versionnées dès le premier schéma, lancées une seule fois au démarrage du moteur (leçon de l'ancien : course entre deux processus).
- **Vecteurs : extension `sqlite-vec`** — maintenue, dans la même base, mêmes transactions. Repli automatique en recherche brute NumPy si l'extension ne charge pas.
- **Graphe : tables `entities` et `relations` dans SQLite, requêtes récursives** — Kùzu, la base graphe embarquée la plus connue, est archivée depuis 2025.
- **Recherche plein texte : FTS5** — combinée aux vecteurs pour une recherche hybride.
- **Embeddings locaux : `multilingual-e5-small` en ONNX quantifié** — bon en français, ~120 Mo, tourne sur ce CPU sans PyTorch.
- **Bus d'événements maison, asynchrone, dans le processus** — une centaine de lignes, typé, testable ; chaque événement est aussi écrit en base pour les automatisations et les traces.
- **Workflows : machine à états persistée en base** — une chaîne reprend à la dernière étape terminée après un crash. Pas de file externe.
- **Pas de LangChain** — adaptateurs fins écrits ici avec les SDK officiels `openai` (DeepSeek, OpenRouter, OpenAI, Ollama via leur API compatible) et `anthropic`. Plus simple à lire et à tester.
- **Sorties structurées** — appel d'outils natif, sinon mode JSON ; validation Pydantic ; parse tolérant (`raw_decode`, puis réparation) ; un seul nouvel essai avec l'erreur ; puis échec propre.
- **Un seul appel LLM par tour** — le modèle répond ou appelle des outils (dont « proposer un plan » et « créer une automatisation ») dans le même appel. L'ancien enchaînait intention, plan puis réponse : trop lent pour la voix.
- **Logs structurés (structlog, JSON) avec ID de corrélation** — et un filtre qui masque toute valeur secrète connue.
- **Client HTTP : `httpx`** — `httpx2` (successeur annoncé par le client de test de Starlette) a été écarté : paquet récent au nom proche de `httpx`, risque d'imitation ; l'avertissement de dépréciation est filtré dans les tests (14/10/2026).
- **Loggers `uvicorn.error` et `websockets` bridés à WARNING** — en DEBUG, ils écrivent le contenu des trames WebSocket, dont le message d'authentification. Le jeton de session est aussi ajouté au filtre des logs.
- **Trousseau en mémoire pour les tests de bout en bout** (`OJARVIS_MEMORY_KEYRING=1`, accepté seulement en mode développement) — aucun test ne touche aux vraies clés, rien n'est écrit en clair.

## LLM

- **DeepSeek en principal** — clé valide ; modèles exposés : `deepseek-flash` et `deepseek-v4-pro`.
- **OpenRouter en offre gratuite** — seuls les modèles `:free` sont utilisables, avec un plafond de requêtes par jour. Suffisant pour la vision en développement.
- **Ollama local : `ministral-3:3b` (3 Go, vision + outils, très bon en français)** — un 7B ferait swapper cette machine. Repli plus léger : `qwen3-vl:2b` (1,9 Go). Chargé à la demande, déchargé vite.
- **OpenAI et Anthropic** — adaptateurs écrits et couverts par des tests de contrat simulés ; ils s'activent seuls quand une clé apparaît.

## Voix

- **Réveil : openWakeWord, modèle `hey_jarvis`** — local ; aucun son ne quitte la machine avant le mot de réveil.
- **Transcription : faster-whisper en français, int8 sur CPU** — taille du modèle (`base` ou `small`) choisie après mesure sur cette machine.
- **Synthèse : Cartesia Sonic `sonic-3.6`, langue `fr`** — vérifié le 14/10/2026 dans la doc officielle et par un appel réel (WAV reçu, premier octet en 114 ms). Repli hors ligne : Piper.
- **Capture et lecture audio : `sounddevice` (PortAudio)** — `libportaudio2` est déjà installé.

## Sécurité

- **Clés dans le trousseau (Secret Service via `keyring`)**, jamais renvoyées à l'interface. Seuls les 12 noms du brief sont importés depuis `.env`.
- **Trois niveaux de permission appliqués par une seule couche** — lire, agir (validation), détruire ou s'étendre (sandbox puis double confirmation).
- **Journal immuable** — table en ajout seul (triggers SQLite qui refusent UPDATE et DELETE), chaînée par SHA-256, vérifiée au démarrage.
- **Sandbox : Docker sans réseau, limites CPU, mémoire, PID et durée, nettoyage garanti** ; bubblewrap en repli.

## Interface

- **pnpm** pour le frontend — déjà installé, rapide.
- **TypeScript 6.0** — TypeScript 7 (compilateur natif) n'est pas encore pris en charge par `typescript-eslint` (< 6.1).
- **Tauri confirmé, pas d'Electron (14/10/2026)** — sphère mesurée dans l'app réelle (WebKitGTK, Intel HD 4600, Wayland, toile de 363 px) : 59,7 à 60,0 i/s selon l'état, p95 ≤ 19 ms, au plus 1 image longue sur 360.
- **Sphère en WebGL2 avec un shader maison** — nuage de points (spirale de Fibonacci), cœur et halo sur un quadrilatère, anneaux en pointillés. Plus léger que three.js. Couleurs lues dans les tokens CSS.
- **Repli sans WebGL** — un disque lumineux en CSS qui garde les couleurs d'état.
- **CSS Modules + tokens** — Stylelint refuse toute couleur hors de `tokens.css`. Seule exception : la couleur de fond de la fenêtre native dans `tauri.conf.json`, copie de `--color-bg`, pour éviter un flash blanc à l'ouverture.
- **Radix UI** pour les dialogues et boutons radio accessibles, **lucide** pour les icônes, **TanStack Query** pour les données du moteur, **Zustand** pour l'état de connexion.
- **Routeur à hachage** — une app de bureau n'a pas de serveur pour réécrire les URL.
- **Polices embarquées (`@fontsource`)** : Inter, Space Grotesk, JetBrains Mono — l'app fonctionne hors ligne (leçon de l'ancien : polices Google bloquées au build).
- **Journal de l'interface vers la coque** (`ui_log`) — les erreurs de la fenêtre arrivent dans les logs même si le moteur est arrêté.

## Qualité

- **Tests de bout en bout : Playwright sur l'interface branchée au vrai moteur**, avec audit axe à chaque écran. La mesure de fluidité, elle, se fait dans l'app Tauri réelle.
- **Audit npm : dépendances livrées strictement propres** ; une faille « haute » sans correctif existe dans `braces`, utilisé seulement par Stylelint au moment du lint, sur nos propres fichiers : aucun contenu externe ne l'atteint. Risque accepté et surveillé (la CI bloque au niveau critique pour les outils de développement).
