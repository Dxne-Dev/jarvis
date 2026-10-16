# Checklist manuelle

Ce que je ne peux pas vérifier seul. Coche au fur et à mesure.

## Phase 1 — Fondations

- [ ] Dans le menu des applications, « O-jarvis » apparaît avec son icône (après `scripts/install-launcher.sh`).
- [ ] Un clic sur l'icône ouvre la fenêtre ; la sphère respire au centre.
- [ ] L'icône O-jarvis est visible dans la barre du haut ; son menu propose « Ouvrir O-jarvis » et « Quitter ».
- [ ] Fermer la fenêtre arrête tout : `pgrep -f "python -m ojarvis"` ne renvoie plus rien.
- [ ] Réglages → une clé → « Vérifier » affiche « Vérifiée » avec sa durée.

## Phase 2 — Parler à Jarvis

- [ ] Après `scripts/install-launcher.sh`, lancer O-jarvis par son icône : GNOME demande d'autoriser le raccourci « Parler à Jarvis » (Ctrl+Alt+J) ; accepter.
- [ ] Ctrl+Alt+J depuis une autre fenêtre : la sphère passe en « J'écoute ».
- [ ] Dire « Hey Jarvis » dix fois, à un mètre du micro, à ton rythme habituel : noter combien réveillent Jarvis (Réglages → Voix → Sensibilité « Haute » si c'est moins de 8).
- [ ] « Hey Jarvis, quelle heure est-il ? » : la réponse parlée commence en moins de 3 s, les sous-titres suivent la voix.
- [x] Dix phrases à ton rythme, à un mètre : « Tu as dit » affiche ce que tu as vraiment dit (transcription Groq). Vérifié par Octave le 15/10 : environ 90 %.
- [ ] Pendant une longue réponse (« Hey Jarvis, raconte-moi une histoire »), parler par-dessus : Jarvis se tait et écoute (haut-parleurs, sans casque).
- [ ] Parler pendant une minute d'autre chose, sans dire « Hey Jarvis » : Jarvis ne se réveille pas.
- [ ] Couper le Wi-Fi puis poser une question : la voix locale (Piper) répond, et une notification le signale si la fenêtre est en arrière-plan.
- [ ] Réglages → Voix : changer de micro, puis de timbre de voix ; la question suivante utilise le nouveau choix.
- [ ] Fermer l'app : `pactl list short modules | grep echo-cancel` ne renvoie plus rien.

## Phase 3 — Jarvis agit

- [ ] Réglages → Navigateur → « Te connecter à un site » : taper un site où tu as un compte (ex. `github.com`), te connecter dans la fenêtre qui s'ouvre, la fermer : le domaine apparaît dans « Domaines autorisés ».
- [ ] Demander « Ouvre mes notifications GitHub et résume-les » : Jarvis propose un plan (niveau 2, ta session) ; après validation, il résume.
- [ ] Réglages → Navigateur → « Importer les cookies d'un domaine » : choisir ton profil Chrome, un domaine où tu es connecté, cocher l'autorisation, « Importer » : le nombre de cookies s'affiche.
- [ ] « Révoquer » ce domaine : il disparaît de la liste, et Jarvis n'y a plus ta session.
- [ ] Demander « Crée le fichier ~/notes/test-jarvis.md avec trois idées de dîner » : un plan attend ; « Refuser » ne crée rien ; redemander et « Valider » le crée.
- [ ] Demander de supprimer ce fichier : la validation demande une seconde confirmation ; le fichier part à la corbeille.
- [ ] Journal et traces → Actions : chaque décision et chaque action y est, « chaîne d'empreintes intacte ».
- [ ] Fenêtre en arrière-plan, demander une action par la voix : une notification « Action à valider » apparaît.

## Phase 4 — Jarvis s'organise

- [ ] Depuis ton téléphone, écrire « Bonjour Jarvis » à @ojarvi_bot (app ouverte sur le PC) : il répond.
- [ ] Envoyer un message vocal à @ojarvi_bot : il affiche ce qu'il a compris, puis répond.
- [ ] Depuis Telegram, demander « Crée le fichier ~/notes/telegram.md avec : test » : deux boutons arrivent ; « Valider » crée le fichier.
- [ ] Depuis un autre compte Telegram (celui d'un proche), écrire au bot : aucune réponse.
- [ ] Réglages → Intégrations → Google Agenda → « Connecter » : accepter dans le navigateur, puis demander « Qu'est-ce que j'ai dans mon agenda aujourd'hui ? ».
- [ ] (Facultatif) Activer « Google Calendar MCP API » dans ton projet Google Cloud, puis « Reconnecter » Google Agenda : l'état indique « serveur officiel de Google ».
- [ ] Dire « Hey Jarvis, rappelle-moi dans dix minutes de m'étirer » : valider le plan ; le rappel arrive à l'heure (app et téléphone).
- [ ] Le lendemain matin, ouvrir l'app : le briefing se dit à voix haute.
- [ ] Laisser une automatisation « chaque jour à … » active, éteindre le PC à l'heure dite, le rallumer moins de 6 h après : elle est rattrapée.

## Phase 5 — Contrôle du PC

- [ ] Réglages → Contrôle du PC : il est « Désactivé » ; « Activer… » ouvre une confirmation ; « Annuler » ne change rien ; « Activer » l'active.
- [ ] Dire « Hey Jarvis, ouvre la calculatrice » : un plan attend ; après « Valider », la calculatrice s'ouvre.
- [ ] « Ferme la calculatrice » : un plan attend ; après « Valider », elle se ferme.
- [ ] Avec une page ou un document ouvert, dire « Hey Jarvis, regarde mon écran » : la description (lecture sur ce PC, compter 30 s à 2 min) correspond à ce que tu vois.
- [ ] Choisir « En ligne », redemander : la réponse arrive plus vite (ou, si OpenRouter est saturé, la lecture repasse sur ce PC).
- [ ] Désactiver le contrôle du PC, redemander « ouvre la calculatrice » : Jarvis répond qu'il ne peut pas.

## Phase 6 — Jarvis s'étend

- [ ] Demander « Crée-toi un skill qui convertit des degrés Fahrenheit en Celsius » : Skills et plugins montre le code, les tests réussis ; la confirmation (deux fois) l'active ; « combien font 100 °F ? » utilise le skill.
- [ ] Skills et plugins → chercher « wikipedia » → Essayer → Installer… : le serveur apparaît « Prêt » ; demander « que dit Wikipédia de Ouidah ? ».
- [ ] (Si Docker est démarré) refaire l'essai : le serveur tourne en conteneur (`docker ps` pendant l'essai).
- [ ] Agents : confier au coach « explique-moi les closures en JavaScript » ; la mission apparaît en direct, puis son compte rendu.
- [ ] Parler de tes projets et de tes proches pendant quelques jours : Mémoire → Graphe les relie ; corriger ou oublier une entité.
- [ ] Après avoir posé la même question trois jours différents, une suggestion apparaît à l'accueil ; « En faire une automatisation » ouvre une conversation avec un plan à valider.

## Phase 7 — Release

- [ ] `sudo apt install ./O-jarvis_1.0.0_amd64.deb` (version GitHub `v1.0.0`, ou `app/src-tauri/target/release/bundle/deb/`) : O-jarvis apparaît dans le menu des applications ; un clic l'ouvre, la sphère respire, « Moteur connecté ».
- [ ] Sur une session neuve (un autre compte Ubuntu, ou après avoir renommé `~/.local/share/o-jarvis`) : renseigner une clé DeepSeek dans Réglages, poser une question : la réponse arrive ; la voix se prépare (téléchargement des modèles), puis « Hey Jarvis » répond.
- [ ] Réglages → Démarrage → activer « Lancer O-jarvis à l'ouverture de session », se déconnecter puis se reconnecter : l'icône est dans la barre système, sans fenêtre ; « Hey Jarvis » répond ; le briefing se joue si c'est la première session du jour.
- [ ] Désactiver le démarrage automatique : `~/.config/autostart/O-jarvis.desktop` disparaît.
- [ ] L'AppImage (même version GitHub) se lance d'un double clic après `chmod +x`.
- [ ] Demander une action dans le navigateur de Jarvis la première fois : Chromium se télécharge (une minute environ), puis l'action se fait.
- [ ] `sudo apt remove o-jarvis` : l'app disparaît du menu ; tes données restent dans `~/.local/share/o-jarvis` (à effacer à la main si tu le veux).
