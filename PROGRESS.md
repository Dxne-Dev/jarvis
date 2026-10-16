# Avancement

## Phase en cours

**7 — Release (version 1.0.0).** Terminée : l'app du `.deb` marche entièrement dans une session neuve (dossier personnel, D-Bus, trousseau, affichage et son neufs) : premier lancement, conversation, briefing, voix de bout en bout, démarrage automatique, arrêt propre. Paquets publiés dans la version GitHub `v1.0.0`. Les commits des phases 6 et 7 sont dans la PR #5 (`dev → main`). Prochaine : la suite de tests par niveaux de complexité.

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

### Phase 3 — Jarvis agit (15/10/2026)
- Outils à schéma strict et niveau de permission : recherche web (Tavily), lecture de page, fichiers, code en bac à sable, navigateur, capacités.
- Porte unique des permissions ; plans vérifiés, validés ou refusés (un plan de lecture seule part sans attendre), exécutés étape par étape avec synthèse ; plans interrompus jamais relancés.
- Journal des actions immuable (ajout seul, chaîne SHA-256, vérifié au démarrage), en lecture seule dans l'interface.
- Navigateur de Jarvis : contexte anonyme et contexte « identité », proxy de garde, coffre chiffré, connexion dans sa fenêtre, import de cookies par domaine, révocation.
- Défenses contre l'injection : contenu externe encadré, action toujours en plan, plan signalé, adresse fabriquée validée.
- Interface : Actions à valider, plan dans la conversation, outils utilisés, journal des actions, Réglages → Navigateur et Permissions, notifications.
- Docs : `docs/journal/03-jarvis-agit.md`, `docs/securite.md`, architecture, checklist manuelle.

### Phase 4 — Jarvis s'organise (15/10/2026)
- Automatisations : horaire en heure locale (changements d'heure testés) ou événement ; rappel ou consigne ; création depuis le chat ou la voix (validée) ; CRUD complet dans l'écran Automatisations ; rattrapage après un arrêt ; ponctuelles désactivées après leur passage.
- Moteur de workflows persistant : reprise à l'étape coupée après un plantage ou un redémarrage.
- Notifications dans l'app, sur le bureau et sur Telegram.
- Telegram : texte et vocal, seul ton identifiant servi, validation des plans de niveau 2 par boutons, jamais de niveau 3.
- Intégrations MCP officielles : GitHub, Notion (conteneurs, versions épinglées) ; Google Agenda (OAuth, serveur officiel ou celui de Jarvis).
- Briefing du matin à la première session du jour.
- Docs : `docs/journal/04-jarvis-s-organise.md`, sécurité, architecture, checklist.

### Phase 5 — Contrôle du PC (15/10/2026)
- Applications : index du menu (noms traduits comme dans Ubuntu), ouvrir (`gtk-launch`), fermer (SIGTERM, tes processus seulement, programmes lancés par un script reconnus), voir ce qui est ouvert.
- Écran : portail Wayland, X11 en direct ; « regarde mon écran » lu en local par défaut (Ollama), en ligne au choix avec repli local.
- Fichiers : déplacer, copier, créer un dossier, avec les garde-fous de la phase 3.
- Contrôle du PC désactivé par défaut ; activé après confirmation (Réglages → Contrôle du PC) ; chaque changement journalisé ; Jarvis sait dire où l'activer.
- Docs : `docs/journal/05-controle-du-pc.md`, sécurité, architecture, checklist.

### Phase 6 — Jarvis s'étend (15-16/10/2026)
- Skills : versions, tests en bac à sable, activation par double confirmation, outils utilisés comme les autres ; Jarvis s'en écrit un sur demande et en propose lui-même l'activation.
- Registre MCP officiel : chercher, essayer isolé (Docker, sinon bubblewrap), installer (double confirmation), désactiver, retirer ; clés au trousseau.
- Agents dev, recherche et coach (`BaseAgent`), orchestrateur sans logique métier, état en direct, une trace par mission.
- Mémoire graphe (personnes, projets, événements, lieux, sujets) remplie par l'extraction, vue graphe modifiable.
- Apprentissage (demandes répétées → automatisation ou skill) et anticipation (projet délaissé), avec score de confiance ; jamais d'action seule.
- Docs : `docs/journal/06-jarvis-s-etend.md`, `docs/creer-un-skill.md`, sécurité, architecture, checklist.

### Phase 7 — Release (16/10/2026)
- Moteur embarqué (PyInstaller, dossier de 796 Mo), sans aucune bibliothèque du système ; Chromium téléchargé au premier usage du navigateur.
- Paquets `.deb` (216 Mo) et AppImage (353 Mo) en une commande (`scripts/build-release.sh`) ; le moteur y est ajouté tel quel après Tauri.
- Démarrage automatique à l'ouverture de session (Réglages → Démarrage), discret dans la barre système.
- Corrigé grâce aux tests en session neuve : bulles d'information qui ne disparaissaient pas et cachaient la saisie ; démarrage de plus de 90 s qui n'aboutissait jamais.
- Docs : `CHANGELOG.md`, `RELEASE_NOTES.md`, `docs/ajouter-un-fournisseur.md`, `docs/journal/07-release.md`, README (installation, captures).

## Ensuite

1. Suite de tests par niveaux de complexité (N1 fondamentaux → N5 scénarios réels), vrai modèle, résultats vérifiés automatiquement, tableau dans le README.
2. Mode shell (Jarvis dans un terminal, agents de code), voix au terminal ; autonomie orientée résultats (moteur de missions). Détail : les issues GitHub.
3. Passage du dépôt en public : choisir une licence d'abord (Piper, embarqué, est sous GPL-3.0), puis ton feu vert.

## Problèmes ouverts

- `braces` (outil de lint) a une faille « haute » sans correctif : accepté, voir `DECISIONS.md`.
- Mot de réveil prononcé avec l'accent français d'espeak-ng : non détecté (0/4) ; les voix naturelles le sont. À confirmer au vrai micro (checklist).
- OpenRouter gratuit renvoie souvent 429 : il ne sert que de second repli ; pour l'écran « en ligne », la lecture repasse en local.
- Lecture locale de l'écran lente sur cette machine (30 s à 2 min) : c'est le prix du « rien ne sort ».
- Une application Flatpak ne se ferme pas (son lanceur `flatpak` est protégé) : aucune n'est installée ici ; `flatpak kill` serait la voie.
- Bout en bout : 3 échecs au tout premier passage après des changements (sans doute la première compilation de Vite), puis 3 passages verts de suite ; à surveiller en CI.
- Docker est arrêté sur la machine depuis le 15/10 au soir (`sudo systemctl start docker` pour le relancer) : le bac à sable passe par bubblewrap, les serveurs MCP du registre aussi ; GitHub (serveur en conteneur) attend Docker.
- Serveurs MCP lancés par bubblewrap : ils gardent le réseau, réseau local compris (Docker les en isole mieux).
- Repérage des demandes répétées : le modèle de sens (e5) rapproche fort des demandes « mêmes mots, autre sujet » ; garde-fou par les noms propres, à affiner avec l'usage.
- Paquets vérifiés sur Ubuntu 26.04 seulement (ils demandent glibc ≥ 2.39 et WebKitGTK 4.1).
- AppImage : pas de raccourci global `Ctrl+Alt+J` (le portail ne trouve pas son lanceur, que seul le `.deb` installe).
- Transcription locale (sans clé Groq) : la fin du mot de réveil reste parfois dans le texte (« Parvice, … ») ; la réponse reste juste.

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
| 15/10 | Deuxième essai au vrai micro (Octave) | Ink-2 entend souvent de l'anglais (accent) ; le paramètre de langue est ignoré |
| 15/10 | Vrai pipeline avec Groq Whisper large-v3 (fr imposé) + DeepSeek + Cartesia | 12/12 tours justes, latence médiane 1,9 s, transcription 0,4 s |
| 15/10 | Questions personnelles sur mémoire vide (vrai DeepSeek) | 6/6 « je ne le sais pas encore », aucune invention |
| 15/10 | Troisième essai au vrai micro (Octave), transcription Groq | « tout fonctionne », environ 90 % de précision au réveil et à l'écoute |
| 15/10 | Voix sur la machine réelle (micro, annulation d'écho) | prête en 6 s ; 50 trames en 4 s ; arrêt en 1,1 s, module retiré |
| 15/10 | Moteur : ruff, mypy strict (code + tests), pytest | 0 erreur ; 346 tests ; couverture 91 % |
| 15/10 | Interface : tsc, ESLint, Stylelint, Prettier, Vitest | 0 erreur ; 36 tests |
| 15/10 | Coque : fmt, clippy `-D warnings`, cargo test | 0 erreur |
| 15/10 | Bout en bout Playwright + vrai moteur + axe | 11/11, dont un tour vocal (audio simulé) ; aucune violation sérieuse |
| 15/10 | `pip-audit` / `pnpm audit --prod` / `cargo audit` | aucune faille ; 2 avertissements GTK acceptés (voir DECISIONS) |
| 15/10 | Démarrage à froid (clone neuf de `dev`, `install-dev.sh`, dossier vierge) | moteur prêt en 7,8 s ; voix prête en 35 s avec téléchargement et vérification des modèles (350 Mo) ; arrêt en 1,1 s |
| 15/10 | Revue de sécurité (section 7) | clé collée dans le chat envoyée au modèle et stockée en clair : corrigé (masquage central) ; noms de périphériques passés à `pactl` : validés |
| 15/10 | CI GitHub : moteur, interface, bout en bout, coque | vertes |
| 15/10 | Plan navigateur de bout en bout (vraie interface, vrai moteur, vrai Chromium, boutique locale) | plan proposé, validé, 3 étapes faites, synthèse « 4,50 € », journal intègre |
| 15/10 | Banc « Jarvis agit » avec le vrai DeepSeek | 5/5 : plan navigateur validé puis exécuté, page piégée ignorée, fichier écrit après validation, recherche web, code en bac à sable |
| 15/10 | Page piégée (supprimer un fichier, fuite par adresse) avec le vrai modèle | 5/5 sans effet : fichier intact, aucune requête de fuite |
| 15/10 | Redirection d'une page publique vers une adresse privée (navigateur) | bloquée (après correctif : proxy de garde) |
| 15/10 | Bac à sable Docker et bubblewrap | sans réseau, dossier perso invisible, temps et mémoire bornés, conteneur supprimé |
| 15/10 | Latence vocale avec les outils | médiane 1,93 s (6/6 tours) |
| 15/10 | Moteur : ruff, mypy strict, pytest | 0 erreur ; 465 tests ; couverture 91 % |
| 15/10 | Interface : tsc, ESLint, Stylelint, Prettier, Vitest | 0 erreur ; 44 tests |
| 15/10 | Bout en bout Playwright + vrai moteur + axe | 14/14 ; aucune violation sérieuse |
| 15/10 | `pip-audit` / `pnpm audit --prod` | aucune faille |
| 15/10 | Revue de sécurité (section 7) | redirection privée, fuite par adresse fabriquée, double résolution DNS de `lire_page`, `~` hors du dossier configuré : corrigés |
| 15/10 | Automatisation après un redémarrage (échéance passée de 10 min) | rattrapée, horaire conservé ; workflow coupé repris à l'étape interrompue |
| 15/10 | « 8 h » à travers les changements d'heure 2026 | 8 h locale les deux fois ; heure inexistante → +1 h ; heure doublée → une seule fois |
| 15/10 | Briefing : première session du jour, le lendemain, désactivé | joué une fois ; rejoué le lendemain ; muet si désactivé (réécoutable) |
| 15/10 | Telegram (API simulée) | inconnu ignoré et journalisé ; texte et vocal traités ; plan de niveau 2 validé par bouton ; niveau 3 refusé même forgé |
| 15/10 | Vrai bot Telegram | @ojarvi_bot joignable, aucun webhook, identifiant autorisé présent |
| 15/10 | Vrais serveurs MCP | GitHub : 48 outils (27 lecture, 18 action, 3 destruction), compte reconnu ; Notion : 24 outils |
| 15/10 | Vrai DeepSeek : automatisations, GitHub, briefing | « tous les matins à 8 h » et « demain à 9 h » justes ; issues lues par MCP ; briefing avec données GitHub |
| 15/10 | Moteur : ruff, mypy strict (code, tests, bancs), pytest | 0 erreur ; 512 tests ; couverture 91 % |
| 15/10 | Interface : tsc, ESLint, Stylelint, Prettier, Vitest | 0 erreur ; 48 tests |
| 15/10 | Bout en bout Playwright + vrai moteur + axe | 16/16 ; aucune violation sérieuse |
| 15/10 | `pip-audit` | aucune faille (mcp 2.3, jsonschema 4.26) |
| 15/10 | Capture d'écran par le portail Wayland (machine réelle) | 1366 × 768 en 4,1 s, sans boîte de dialogue ; fichier effacé |
| 15/10 | Banc « application » avec le vrai DeepSeek | désactivé : il le dit et indique Réglages ; activé : plan, validation, calculatrice ouverte puis fermée |
| 15/10 | Banc « écran » sur une capture de test (total 1 045 €) | local : juste en 30 s ; en ligne : OpenRouter 429 → repli local juste en 136 s |
| 15/10 | Sécurité du contrôle du PC | désactivé par défaut ; outils refusés et invisibles ; écran piégé → plan signalé en attente ; changements journalisés ; processus protégés |
| 15/10 | Moteur : ruff, mypy strict, pytest | 0 erreur ; 532 tests ; couverture 89 % |
| 15/10 | Interface : tsc, ESLint, Stylelint, Prettier, Vitest | 0 erreur ; 49 tests |
| 15/10 | Bout en bout Playwright + vrai moteur + axe | 17/17 ; aucune violation sérieuse |
| 15/10 | `pip-audit` / `pnpm audit --prod` | aucune faille (pillow, mss, jeepney compris) |
| 15/10 | Banc « skill » avec le vrai DeepSeek | skill « jours-entre-dates » écrit, 10/10 tests dans le bac à sable, activation par double confirmation, puis « 287 jours » par son outil |
| 15/10 | Banc « mcp » (vrai registre, vrai DeepSeek) | serveur Wikipédia trouvé, installé après double confirmation (bubblewrap), puis utilisé pour répondre sur Cotonou |
| 15/10 | Banc « agents » avec le vrai DeepSeek | l'agent de recherche cherche et lit seul (14 appels), compte rendu rendu à Jarvis |
| 15/10 | Similarité e5 des demandes (mesure) | paraphrases 0,97-0,98 ; sans rapport ≤ 0,88 ; « autre projet » 0,96-0,97 → seuil 0,95 + mêmes noms propres |
| 16/10 | Moteur : ruff, mypy strict, pytest | 0 erreur ; 558 tests |
| 16/10 | Interface : tsc -b, ESLint, Stylelint, Prettier, Vitest | 0 erreur ; 63 tests |
| 16/10 | Bout en bout Playwright + vrai moteur + axe | 20/20 ; aucune violation sérieuse |
| 16/10 | `pip-audit` / `pnpm audit --prod` | aucune faille |
| 16/10 | Revue de sécurité (section 7) | liste des outils d'un serveur MCP non encadrée, schéma d'un skill sans limite de taille : corrigés |
| 16/10 | Moteur : ruff, mypy strict, pytest | 0 erreur ; 563 tests ; couverture 89 % |
| 16/10 | Interface : tsc -b, ESLint, Stylelint, Prettier, Vitest | 0 erreur ; 66 tests |
| 16/10 | Coque : fmt, clippy `-D warnings`, cargo test | 0 erreur ; 8 tests |
| 16/10 | `pip-audit` / `pnpm audit --prod` / `cargo audit` | aucune faille ; les 2 avertissements GTK déjà acceptés |
| 16/10 | Contenu des paquets | `.deb` 216 Mo (sommes justes, fichiers à root, 57 liens conservés), AppImage 353 Mo ; même moteur ; aucune des 32 valeurs du `.env` ; glibc ≥ 2.39 |
| 16/10 | Session neuve, app du `.deb` | clé importée au trousseau ; modèles téléchargés (335 Mo) ; briefing joué ; réponses en 1,1 à 1,8 s ; démarrage automatique créé puis retiré ; moteur arrêté 0,65 s après l'app |
| 16/10 | Voix dans la session neuve (PipeWire privé, sans matériel) | « combien font douze fois huit ? » → « 96 » dit à voix haute ~3,7 s après la question (voix 100 % locale) ; annulation d'écho en place |
| 16/10 | AppImage lancée comme au démarrage de session | aucune fenêtre, moteur prêt en 11 s, micro ouvert ; second lancement → fenêtre ; démarrage automatique vers l'AppImage |
| 16/10 | Moteur retardé de 100 s | l'app annonce le retard à 91 s (« il tarde à répondre… »), puis se connecte seule dès que le moteur est prêt (107 s) |
| 16/10 | Bout en bout Playwright + vrai moteur + axe | 20/20 ; aucune violation sérieuse |
| 16/10 | Revue de sécurité (section 7) | permissions de la fenêtre au minimum (démarrage automatique seul) ; aucun script exécuté à l'installation du `.deb` ; aucun secret ni bibliothèque système dans les paquets ; Piper sous GPL-3.0 noté pour le choix de licence |
