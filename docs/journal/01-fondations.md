# 01 — Fondations

## Ce qui a été construit

- **Le moteur Python** (`engine/`) : une API FastAPI qui n'écoute que `127.0.0.1`, protégée par un jeton tiré à chaque lancement. Il garde les clés dans le trousseau GNOME, publie des événements, trace chaque requête et écrit des logs JSON filtrés.
- **L'app** (`app/`) : une coque Tauri (Rust) qui lance le moteur, l'arrête à la fermeture et met une icône dans la barre système. L'interface React affiche trois écrans : Accueil (la sphère), Journal et traces, Réglages.
- **La sphère** : un nuage de 3 400 points lumineux en WebGL2, avec six états (veille, écoute, réflexion, parole, validation, erreur) et des transitions douces.
- **La CI** (`.github/workflows/ci.yml`) : lint, typage, tests et audits pour Python, TypeScript et Rust, plus les tests de bout en bout.
- **Deux scripts** : `scripts/install-dev.sh` (tout installer sans sudo) et `scripts/install-launcher.sh` (le lanceur « un clic »).

Le schéma et le démarrage pas à pas sont dans [`../architecture.md`](../architecture.md).

## Les décisions qui comptent

**Le jeton passe par l'entrée standard.** Une variable d'environnement se lit dans `/proc/<pid>/environ` ; l'entrée standard, non. Et comme l'app garde ce flux ouvert, sa fermeture sert aussi de signal d'arrêt : si l'app plante, le moteur s'arrête seul.

**Le moteur choisit son port.** Il s'attache au port 0 (le système en donne un libre), puis l'annonce. Aucune collision possible avec un autre programme.

**Une clé ne revient jamais.** L'API sait enregistrer, vérifier et supprimer une clé, jamais la relire. L'écran Réglages affiche « Configurée », jamais la valeur.

**Tauri plutôt qu'Electron.** Le brief imposait une mesure : la sphère tient 60 images par seconde dans la vraie app, sur la carte graphique intégrée de cette machine.

| État | i/s | p95 |
|---|---|---|
| Veille | 59,7 | 19 ms |
| Écoute | 60,0 | 18 ms |
| Réflexion | 60,0 | 17 ms |
| Parole | 59,8 | 18 ms |
| Validation | 60,0 | 17 ms |
| Erreur | 60,0 | 17 ms |

**Les couleurs n'existent qu'à un endroit.** `app/src/styles/tokens.css` définit tout ; Stylelint refuse une couleur écrite ailleurs. Même la sphère lit ses couleurs dans ces tokens.

## Ce que les tests ont attrapé

- Un **fragment du jeton** apparaissait dans les logs de debug : la bibliothèque WebSocket écrivait le contenu des trames. Ses logs sont maintenant bridés, et le jeton est ajouté au filtre.
- Au démarrage, le chargement des clés **remplaçait** la liste des valeurs à masquer, au lieu de la compléter : le jeton de session n'était plus masqué. Corrigé, et couvert par un test.
- Le **garde-fou git** a bloqué un commit : une fausse clé de test avait le format d'une vraie. Les valeurs de test ne ressemblent plus à des clés.
- En développement, React monte deux fois chaque effet : la mesure de fluidité s'annulait elle-même. Corrigé.

## Vérifié

- Moteur : 155 tests, couverture 93 %, ruff et mypy strict sans erreur, `pip-audit` sans faille.
- Interface : 34 tests, TypeScript, ESLint et Stylelint sans erreur.
- Bout en bout (Playwright + vrai moteur) : 6 scénarios, dont ajout, vérification et suppression d'une clé, navigation au clavier, largeur 900 px et animations réduites ; audit axe sans violation sérieuse.
- Coque : `cargo fmt`, `clippy -D warnings` et 5 tests sans erreur.
- App réelle : le moteur démarre et s'arrête avec elle ; la sphère tient 60 i/s.
