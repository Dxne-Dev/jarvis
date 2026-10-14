# Checklist manuelle

Ce que je ne peux pas vérifier seul. Coche au fur et à mesure.

## Phase 1 — Fondations

- [ ] Dans le menu des applications, « O-jarvis » apparaît avec son icône (après `scripts/install-launcher.sh`).
- [ ] Un clic sur l'icône ouvre la fenêtre ; la sphère respire au centre.
- [ ] L'icône O-jarvis est visible dans la barre du haut ; son menu propose « Ouvrir O-jarvis » et « Quitter ».
- [ ] Fermer la fenêtre arrête tout : `pgrep -f "python -m ojarvis"` ne renvoie plus rien.
- [ ] Réglages → une clé → « Vérifier » affiche « Vérifiée » avec sa durée.
