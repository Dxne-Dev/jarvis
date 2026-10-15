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
