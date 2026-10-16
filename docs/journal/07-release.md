# 07 — Release

## Ce qui a été construit

- **Le moteur embarqué** (`engine/packaging/`) : PyInstaller transforme le moteur Python et ses dépendances en un dossier autonome, rangé dans les paquets à côté de l'app. Plus besoin d'installer Python : la coque lance `…/engine/ojarvis-engine`.
- **Les paquets** : un `.deb` (Ubuntu, Debian) et une AppImage (un seul fichier, sans installation), construits par `scripts/build-release.sh`.
- **Le démarrage automatique** : Réglages → Démarrage. O-jarvis se lance à l'ouverture de session, discret dans la barre système : « Hey Jarvis » répond, le briefing du matin se joue.
- **Chromium au premier usage** : le navigateur de Jarvis se télécharge la première fois qu'il sert, une seule fois.
- **Les documents de version** : `CHANGELOG.md`, `RELEASE_NOTES.md`, les guides « créer un skill » et « ajouter un fournisseur de modèles ».

## Le trajet d'une version

1. `scripts/build-engine.sh` : PyInstaller construit le moteur (~800 Mo) dans `engine/dist/ojarvis-engine/`.
2. `pnpm tauri build --bundles deb,appimage` : l'app (Rust + interface) dans un `.deb`, avec ses dépendances système, et dans une AppImage.
3. Le moteur est ajouté tel quel aux deux paquets : le `.deb` est ouvert, complété (sommes de contrôle et taille recalculées) et refermé ; l'AppImage est extraite, complétée et refermée.

## Les décisions qui comptent

**Un dossier plutôt qu'un seul fichier.** PyInstaller sait tout mettre dans un exécutable unique, mais il se décompresse alors à chaque lancement (800 Mo) : trop lent pour une app qui démarre avec ta session.

**Les bibliothèques du système restent celles du système.** PyInstaller avait copié celles du son (PulseAudio, ALSA, JACK), de D-Bus, de systemd et de l'affichage : elles parlent à des services de la machine et doivent être à leur version. Elles sont retirées du moteur ; le `.deb` déclare celles dont il a besoin (`libportaudio2`, `pulseaudio-utils`, `libgtk-3-bin`). Leurs dépendances (les codecs de libsndfile) et la base du système (glibc, libstdc++, zlib) aussi : elles restent à jour avec la machine, correctifs de sécurité compris.

**Le moteur ajouté après Tauri, tel quel.** Tauri sait embarquer des fichiers, mais il recopiait les 57 liens symboliques du moteur en vrais fichiers (300 Mo de plus, des bibliothèques en double). Et son outil d'AppImage (`linuxdeploy`) inspecte et retouche chaque bibliothèque : il échouait sur celles, renommées, des roues Python (`libgomp-e985bcbb.so`), que le moteur trouve pourtant très bien. D'où la construction en deux temps.

**Le bon nom pour le bureau.** Le portail de GNOME reconnaît l'app à son fichier `.desktop` (`io.github.octavebahoun.ojarvis.desktop`), nécessaire au raccourci global ; Tauri l'aurait appelé `O-jarvis.desktop`. Le paquet installe donc le bon fichier, et l'autre est masqué.

**Démarrer discret.** Lancée par l'entrée de démarrage automatique (`--au-demarrage`), l'app garde sa fenêtre cachée ; un clic sur l'icône, le menu ou `Ctrl+Alt+J` la montre.

## Ce que les tests ont attrapé

- **`collect_all("mcp")` arrêtait la construction** : il importe aussi `mcp.cli`, qui quitte si `typer` est absent. Le SDK est collecté sans sa ligne de commande.
- **Le paquet nommait mal son lanceur** pour le portail du bureau (voir plus haut).
- **Le `.deb` pesait 300 Mo de trop** : le moteur extrait du paquet comptait 0 lien symbolique contre 57 dans le moteur construit.
- **Une bulle d'information restait à l'écran** (le briefing) : chaque événement du moteur annulait son minuteur. En bas à droite, elle cachait en plus la zone de saisie : elle passe en haut.
- **Un démarrage de plus de 90 s n'aboutissait jamais** : l'app affichait l'échec et ne se connectait plus, alors que le moteur finissait de démarrer (vu avec un trousseau qui attendait une réponse). L'app garde maintenant l'oreille tendue et se connecte dès qu'il est prêt.
- **L'AppImage ne se construisait pas** : Tauri réutilisait ses dossiers de travail (ancien moteur compris), et son lanceur caché n'avait pas de catégorie.
- **Le moteur exigeait la glibc 2.43**, donc Ubuntu 26.04 au minimum, à cause d'une copie de `libmvec` (un morceau de la glibc) tirée par un codec : vu en listant la version de glibc que demande chaque bibliothèque. Sans les copies du système, il se contente de la 2.34.
- **Un paramètre inutilisé dans un test** est passé en local mais pas en CI : la CI lance `tsc -b` (qui vérifie aussi les tests). Les vérifications locales utilisent maintenant les mêmes commandes (`pnpm typecheck`, `pnpm lint`).

## Vérifié

Dans une **session neuve** : dossier personnel, bus D-Bus, trousseau, affichage (Xvfb) et son (un PipeWire privé, sans matériel : ton micro et tes haut-parleurs ne sont jamais ouverts), tous neufs. L'app est celle du `.deb`, extraite telle quelle.

- **Premier lancement** : la clé DeepSeek du `.env` passe au trousseau, les modèles locaux se téléchargent (335 Mo), le briefing du matin se joue.
- **Conversation** : réponse en 1,1 à 1,8 s, titre trouvé tout seul.
- **Voix de bout en bout** : « Hey Jarvis, combien font douze fois huit ? » joué dans le micro virtuel → transcrit en local → « 96 » dit à voix haute, environ 3,7 s après la question. C'est la voix 100 % locale (sans clé Groq ni Cartesia) ; avec elles, la phase 2 mesurait 1,9 s. L'annulation d'écho se met en place toute seule.
- **Démarrage automatique** : l'interrupteur crée puis retire `~/.config/autostart/O-jarvis.desktop` (avec `--au-demarrage`) ; depuis l'AppImage, l'entrée pointe vers l'AppImage elle-même.
- **AppImage** : lancée comme au démarrage de session, aucune fenêtre ne s'ouvre, le moteur est prêt en 11 s et le micro écoute ; un second lancement montre la fenêtre.
- **Arrêt** : fermer l'app arrête le moteur, voix comprise (disparu 0,65 s après).
- **Contenu des paquets** : sommes de contrôle justes, fichiers à root, 57 liens conservés ; le même moteur dans les deux ; aucune des 32 valeurs du `.env` ; aucune bibliothèque du système copiée ; glibc 2.39 au minimum.
- **Démarrage lent** : un moteur retardé de 100 s : l'app annonce le retard à 91 s, puis se connecte seule dès qu'il est prêt (107 s).
- **Contrôles habituels** : moteur (ruff, mypy strict, 563 tests, couverture 89 %), interface (66 tests), coque (8 tests), bout en bout (20/20, audit d'accessibilité sans violation sérieuse), audits sans faille.

Ce qui reste à faire de ton côté (vrai micro, `sudo apt install`, vraie ouverture de session) est dans `docs/checklist-manuelle.md`.
