# 05 — Jarvis contrôle le PC

## Ce qui a été construit

- **Les applications** (`engine/src/ojarvis/desktop/apps.py`) : l'index du menu (les fichiers `.desktop`, avec les noms traduits comme dans le menu d'Ubuntu), ouvrir, fermer, voir ce qui est ouvert.
- **L'écran** (`desktop/screen.py`) : capture par le portail du bureau sous Wayland, directe sous X11 ; l'image est réduite puis lue par un modèle de vision (« regarde mon écran »).
- **Les fichiers** : déplacer, copier, créer un dossier, dans ton dossier personnel, avec les garde-fous de la phase 3.
- **Les outils** (`tools/desktop.py`) portent tous la marque « contrôle du PC » : tant que tu ne l'as pas activé, le modèle ne les voit pas et la porte des permissions les refuse.
- **Réglages → Contrôle du PC** : l'interrupteur (désactivé par défaut, activé après une confirmation) et le choix de la lecture de l'écran (sur ce PC ou en ligne).

## Le trajet de « ouvre la calculatrice »

1. Le modèle appelle `ouvrir_application` : c'est une action (niveau 2), elle devient un plan d'une étape.
2. Le plan dit exactement quoi : « Ouvrir l'application Calculatrice (org.gnome.Calculator) ». Tu valides.
3. La porte vérifie que le contrôle du PC est activé et que la validation porte sur cette étape ; le journal note « Lancé : … ».
4. Jarvis lance `gtk-launch -- org.gnome.Calculator`, comme le menu d'Ubuntu : jamais de shell, jamais la ligne `Exec` lue et exécutée par Jarvis.

## Le trajet de « regarde mon écran »

1. `regarder_ecran` est une lecture (niveau 1) : pas de validation, mais seulement si le contrôle du PC est activé.
2. Sous Wayland (ta session), le portail fait la capture sans boîte de dialogue et l'écrit dans un fichier ; Jarvis la lit, puis l'efface.
3. L'image est réduite (768 px de côté en local, 1 600 px en ligne) et réencodée en JPEG.
4. En local (le réglage par défaut), `ministral-3:3b` la lit dans Ollama : rien ne sort de la machine. En ligne, c'est un modèle de vision d'OpenRouter ; s'il est saturé, la lecture repasse en local.
5. La description revient au modèle principal encadrée comme une donnée : un texte affiché à l'écran ne peut pas donner d'ordre.

## Les décisions qui comptent

**Désactivé par défaut, activé par toi.** C'est la règle du brief. L'activer passe par une confirmation qui dit ce que Jarvis pourra faire ; le désactiver est immédiat. Chaque changement est écrit au journal, comme toute décision sur une permission.

**L'écran est lu en local par défaut.** Ton écran peut montrer un mot de passe, un message privé, une clé : aucun filtre ne sait masquer un secret dans une image. En local, rien ne sort ; c'est lent sur cette machine (30 s quand le modèle est chargé, plus de 2 min sinon) mais juste. « En ligne » est un choix explicite, rapide quand OpenRouter répond.

**Le portail, la seule voie sous Wayland.** Une application ne peut pas lire l'écran directement sous Wayland (et GNOME 50 n'a plus de session X11) : le portail `org.freedesktop.portal.Screenshot` est prévu pour ça. Le chemin X11 reste, testé sous Xvfb.

**Fermer, c'est SIGTERM, et seulement tes processus.** L'application peut demander d'enregistrer avant de partir. Jamais la session, un shell, Python, Jarvis lui-même, ni un lanceur partagé (`flatpak`, `snap`). Quand une application démarre par un script (Chrome, LibreOffice, VS Code), le programme qui tourne porte un autre nom : Jarvis le reconnaît à son dossier. Si d'autres entrées du menu partagent ce programme (Chrome et ses applis web), l'écran de validation le dit : tout se fermera ensemble.

## Ce que les tests ont attrapé

- **« Ouvre la calculatrice » ne trouvait rien** (banc avec le vrai modèle). Sous Ubuntu, la plupart des fichiers `.desktop` disent « Calculator » : le nom français vient d'un catalogue de traductions (gettext). Les noms sont maintenant traduits comme dans le menu, et le nom anglais reste reconnu.
- **Chrome « n'était pas ouvert »** alors que 25 de ses processus tournaient : `google-chrome` est un script qui lance `chrome`.
- **La lecture locale échouait juste après le démarrage** : Ollama n'avait pas encore été revérifié. Une demande qui doit rester locale le revérifie d'abord (au plus une fois par minute).
- **OpenRouter gratuit répondait « trop de requêtes »** : l'écran est relu en local, avec l'image réduite pour le petit modèle (en 1 600 px, il aurait dépassé son délai).

## Vérifié

- **Une application s'ouvre après validation** : vrai DeepSeek, vraie calculatrice ; plan proposé, validé, application ouverte, puis fermée sur demande (banc `application`).
- **« Regarde mon écran » décrit correctement une capture de test** (un tableur, total 1 045 €) : juste en local (30 s) ; en ligne, OpenRouter saturé, repli local juste (136 s, modèle à charger).
- Capture réelle par le portail : 1366 × 768 en 4,1 s, sans boîte de dialogue. X11 : capture sous Xvfb, aussi en CI.
- **Sécurité** : contrôle désactivé par défaut ; outils invisibles pour le modèle et refusés par la porte tant qu'il l'est ; un écran piégé (« ferme Firefox ») ne déclenche qu'un plan signalé qui attend ; dossiers sensibles hors d'atteinte pour les fichiers ; activer, désactiver ou envoyer l'écran en ligne est journalisé.
- Moteur : 532 tests, couverture 89 %. Interface : 49 tests. Bout en bout : 17 scénarios, dont le contrôle du PC (confirmation, journal, axe).
