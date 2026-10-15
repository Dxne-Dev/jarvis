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
- **Client HTTP : `httpx`** — `httpx2` (successeur annoncé par le client de test de Starlette) a été écarté : paquet récent au nom proche de `httpx`, risque d'imitation ; l'avertissement de dépréciation est filtré dans les tests (14/10/2026). Il arrive quand même comme dépendance des SDK officiels `anthropic` 1.x et `huggingface-hub` ; notre code n'utilise que `httpx` (15/10/2026).
- **Flux d'événements WebSocket : groupe de tâches anyio** — avec `asyncio.gather`, l'annulation venue de l'extérieur n'était pas toujours reconnue et faisait échouer un test de temps en temps (15/10/2026).
- **Loggers `uvicorn.error` et `websockets` bridés à WARNING** — en DEBUG, ils écrivent le contenu des trames WebSocket, dont le message d'authentification. Le jeton de session est aussi ajouté au filtre des logs.
- **Trousseau en mémoire pour les tests de bout en bout** (`OJARVIS_MEMORY_KEYRING=1`, accepté seulement en mode développement) — aucun test ne touche aux vraies clés, rien n'est écrit en clair.

## LLM

- **DeepSeek en principal** — clé valide ; modèles exposés : `deepseek-flash` et `deepseek-v4-pro`.
- **OpenRouter en offre gratuite** — seuls les modèles `:free` sont utilisables, avec un plafond de requêtes par jour. Suffisant pour la vision en développement.
- **Ollama local : `ministral-3:3b` (3 Go, vision + outils, très bon en français)** — un 7B ferait swapper cette machine. Repli plus léger : `qwen3-vl:2b` (1,9 Go). Chargé à la demande, déchargé vite.
- **OpenAI et Anthropic** — adaptateurs écrits et couverts par des tests de contrat simulés ; ils s'activent seuls quand une clé apparaît.
- **Délai maximal avant le premier morceau de réponse, par tâche** — 5 s pour la voix, 20 s pour le chat, 120 s pour un modèle local (chargement). Le 15/10/2026, DeepSeek acceptait les requêtes sans jamais répondre (incident de leur côté) : sans ce délai, un tour vocal attendait sans fin.
- **Modèle local préchargé quand un fournisseur en ligne tombe** — son premier chargement prend 13 à 50 s ; au plus une fois toutes les 5 minutes.
- **Rien n'est appris d'une transcription douteuse** — log-probabilité moyenne de Whisper sous -0,6 : Jarvis répond (et demande de répéter) mais n'extrait aucun fait. Mesuré sur le corpus : phrases ratées sous -1, bonnes au-dessus de -0,7. Sans ce garde-fou, un faux prénom tiré d'une phrase mal entendue s'installait en mémoire.

## Voix

- **Tout est local avant la réponse** — réveil, détection de parole et transcription tournent sur la machine ; seul le texte part vers le modèle et vers Cartesia. Aucun son ne quitte la machine, ni avant ni après le mot de réveil.
- **Réveil en deux temps : openWakeWord `hey_jarvis`, puis vérification locale** — le modèle est entraîné sur l'anglais : prononcé « à la française », « Jarvis » obtient un score moyen. Score ≥ 0,5 : réveil. Entre 0,15 et 0,5 : les 2 dernières secondes sont transcrites en local et l'on y cherche « Jarvis », même écorché (« Jarvi », « Jervus »…). Corpus du 15/10 : 17 réveils sur 21 (11/11 prononcés à l'anglaise, 6/6 à la française par Cartesia dont 3 grâce à la vérification, 0/4 pour espeak-ng à l'accent français), aucun faux réveil sur les phrases sans mot de réveil. Coût : ~4 ms par trame de 80 ms.
- **openWakeWord sans TFLite** — sa dépendance `tflite-runtime` n'existe pas pour Python 3.12 ; elle est retirée de ses métadonnées (`[tool.uv.dependency-metadata]`), le modèle tourne en ONNX.
- **Détection de parole : Silero VAD v6, fourni avec faster-whisper** — rien à télécharger. Fin de phrase après 0,6 s de silence ; dès 0,2 s, la transcription démarre en avance (jetée si la parole reprend).
- **Transcription : Whisper `base` int8, fenêtre de 10 s au lieu de 30 s** — mesuré ici : `small` prend ~5 s, trop lent ; `base` prend 1,3 à 1,7 s sur la fenêtre de 30 s imposée par Whisper, et 0,45 s sur une fenêtre de 10 s, pour une transcription quasi identique. Repli automatique sur la méthode standard en cas d'erreur.
- **Synthèse : Cartesia Sonic `sonic-3.6` en flux (WebSocket)** — connexion ouverte dès le mot de réveil (250 ms gagnées), première phrase envoyée sans tampon (premier son en ~90 ms), clé en en-tête et jamais dans l'URL. Voix par défaut « Étienne » (masculine, posée), modifiable dans Réglages.
- **Repli : Piper `fr_FR-tom-medium`** — si Cartesia échoue, même au milieu d'une réponse, Piper reprend à la phrase en cours ; Cartesia est ensuite mis de côté une minute. Réglage « tout local » possible.
- **Réponse découpée en phrases au fil de l'eau** — la voix commence pendant que le modèle écrit ; la première proposition part dès qu'elle est complète ; le markdown est retiré.
- **Latence mesurée (15/10/2026)** — de la fin réelle de la phrase au premier son : médiane 1,75 s, maximum 1,9 s, sur 17 tours avec DeepSeek et Cartesia (objectif : moins de 3 s).
- **Capture et lecture : `sounddevice` (PortAudio, hôte PulseAudio)** — périphériques choisis par leur nom PipeWire. La liste vient de `pactl` : réinitialiser PortAudio pendant l'écoute coupait le micro sans erreur. Un micro muet 3 s est signalé et relancé.
- **Annulation d'écho : module `echo-cancel` de PipeWire** — chargé par le moteur sans sudo, il crée un micro et une sortie virtuels ; les périphériques par défaut du système ne changent pas ; déchargé à l'arrêt. C'est lui qui permet de couper Jarvis en parlant ; sans lui (ni casque), seul « Hey Jarvis » le coupe, pour qu'il ne s'interrompe pas en s'entendant.
- **Relance sans mot de réveil** — après une réponse, Jarvis écoute encore 6 s ; la conversation continue (même conversation pendant 10 minutes).
- **Pipeline découplé du chat** — un service à part, désactivable dans Réglages ; s'il échoue, le reste du moteur continue.
- **Modèles vocaux téléchargés au premier lancement** (~210 Mo : réveil, Whisper base, voix Piper), à révision figée et vérifiés par SHA-256.

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
- **Journal de l'interface vers la coque** (`ui_log`) — les erreurs de la fenêtre arrivent dans les logs même si le moteur est arrêté. Les caractères de contrôle sont retirés : une ligne ne peut pas en imiter une autre.
- **Permissions de la fenêtre au minimum** — écouter les événements du shell, ouvrir un lien http(s) dans le navigateur, afficher une notification ; `core:default` aurait aussi permis de créer menus et icônes système.
- **Raccourci global par le portail GlobalShortcuts (`ashpd`)** — sous Wayland, c'est le seul moyen d'écouter une touche hors de la fenêtre. Ctrl+Alt+J par défaut ; GNOME demande confirmation au premier lancement. L'app s'annonce au portail sous `io.github.octavebahoun.ojarvis`, d'où le nom du fichier `.desktop` du lanceur.
- **Notifications du bureau seulement fenêtre en arrière-plan** — fournisseur en panne, voix de secours, voix arrêtée.
- **Niveau sonore hors de React** — une douzaine de mesures par seconde, lissées et lues par la sphère à chaque image, sans redessiner l'écran.
- **Sous-titres** — chaque phrase dite par Jarvis s'affiche à l'accueil, au rythme de sa voix.

## Qualité

- **Tests de bout en bout : Playwright sur l'interface branchée au vrai moteur**, avec audit axe à chaque écran. La mesure de fluidité, elle, se fait dans l'app Tauri réelle.
- **Audit Rust (`cargo audit`) en CI** — aucune vulnérabilité au 15/10/2026. Deux avertissements viennent de la pile GTK de Tauri : `proc-macro-error` n'est plus maintenue (outil de compilation) et `glib::VariantStrIter` est non sûre (fonction que le projet n'utilise pas). Acceptés, surveillés.
- **Voix testée sans matériel** — en développement, `OJARVIS_FAKE_AUDIO=1` remplace micro, modèles et haut-parleur par des simulations ; le pipeline, le chat et l'interface restent réels. Les tests du pipeline utilisent une horloge virtuelle (aucune attente).
- **Corpus vocal et banc d'essai** (`engine/tools/`) — « Hey Jarvis, … » dit par Piper, espeak-ng et Cartesia ; le banc rejoue le corpus dans le vrai pipeline (vrais modèles, vrai DeepSeek, vrai Cartesia) et mesure réveil, transcription et latence.
- **Audit npm : dépendances livrées strictement propres** ; une faille « haute » sans correctif existe dans `braces`, utilisé seulement par Stylelint au moment du lint, sur nos propres fichiers : aucun contenu externe ne l'atteint. Risque accepté et surveillé (la CI bloque au niveau critique pour les outils de développement).
