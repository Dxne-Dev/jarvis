# Sécurité et permissions

Jarvis peut lire, agir et détruire pour toi. Cette page dit qui décide de quoi, et comment c'est vérifié.

## Les trois niveaux

| Niveau | Exemples | Qui décide |
|---|---|---|
| 1 · Lecture | chercher sur le web, lire une page ou un fichier, lister un dossier, lancer du code en bac à sable | Jarvis, seul |
| 2 · Action | cliquer, remplir un champ, écrire un fichier, utiliser ta session sur un site, ouvrir ou fermer une application | toi : un plan à valider |
| 3 · Destruction | mettre un fichier à la corbeille, (plus tard) installer un skill, changer une permission | toi, deux fois |

Lire l'écran est une lecture (niveau 1), mais tout ce qui touche au PC (applications, fichiers rangés, écran) n'existe qu'une fois le contrôle du PC activé (voir plus bas).

Le niveau de chaque outil est fixé dans le code et visible dans Réglages → Permissions. Il peut dépendre des arguments : ouvrir une page est de niveau 1, sauf sur un domaine où Jarvis a ta session (niveau 2).

## Une seule porte

Aucun outil ne s'exécute ailleurs que dans `engine/src/ojarvis/permissions/gate.py` :

1. l'outil existe, ses arguments respectent son schéma (aucun champ inconnu) ;
2. son niveau est calculé avec les vrais arguments ;
3. niveau 2 ou 3 : il faut une validation rattachée à une étape d'un plan, et le niveau ne peut pas dépasser celui que tu as vu ; niveau 3 : il faut la double confirmation ;
4. l'action est écrite au journal avant (« Lancé : … ») et après (« Fait : … » ou « Échec : … »).

## Les plans

Le modèle propose un plan avec l'outil `proposer_un_plan`. S'il appelle directement une action, elle devient un plan d'une étape : rien n'est exécuté sur un simple appel. Avant d'être montré, le plan est vérifié : outils connus, arguments valides, et **la cible d'une action est connue** (une adresse ou un fichier ne peut pas venir du résultat d'une étape précédente ; seul un contenu, comme le texte à écrire, le peut).

À l'écran : ce qui va se passer, sur quoi, à quel niveau ; « Refuser » et « Valider » côte à côte, de même taille. Un plan coupé par un arrêt du moteur n'est jamais relancé seul.

La validation suit le niveau : un plan qui ne fait que lire (niveau 1) part sans attendre, comme un outil de lecture, sauf s'il est proposé après la lecture d'un contenu externe ; dans ce cas, il attend ta décision.

## Le contenu externe est une donnée

Ce qui vient d'une page, d'un fichier ou d'un résultat d'outil arrive au modèle encadré par `<donnees>…</donnees>`, avec la consigne de n'y suivre aucun ordre. Une fausse balise de fermeture dans la page est neutralisée.

Si le contenu pousse quand même le modèle à agir :
- l'action devient un plan, **signalé** (« proposé après la lecture d'un contenu externe ») ;
- ouvrir une adresse absente de ta demande et des pages lues (une adresse fabriquée pour faire fuir des données) demande aussi ta validation.

Testé avec des pages piégées, en simulation (`tests/test_agent_chat.py`) et avec le vrai modèle (`engine/tools/agent_bench.py`).

## Le réseau

Le navigateur de Jarvis et la lecture de pages passent par un proxy local (`browser/proxy.py`). Il résout le nom, vérifie que **toutes** les adresses sont publiques, puis se connecte lui-même à l'adresse vérifiée : pas de box, pas de `127.0.0.1`, pas de réseau local, même par une redirection ou une réponse DNS qui change.

## Tes sessions et tes cookies

- Le navigateur de Jarvis n'est jamais le tien. Pour lire, il n'a aucun cookie.
- Un domaine n'est autorisé que par toi (Réglages → Navigateur) : en te connectant dans sa fenêtre, ou en important les cookies **de ce domaine** depuis Chrome, Chromium ou Brave, avec une case à cocher explicite. Révocable à tout moment.
- Les sessions sont gardées dans un coffre chiffré, avec une clé dérivée de la clé locale du trousseau. Ni les cookies ni leur valeur ne vont à un modèle ou à l'interface.
- Jarvis ne remplit jamais un mot de passe, un numéro de carte ou un code à usage unique.

## Les fichiers

Seulement dans ton dossier personnel, et jamais dans : `.ssh`, `.gnupg`, trousseaux, profils de navigateurs, `.aws`, `.kube`, `.docker`, la configuration de `gh`, les données d'O-jarvis ; ni les fichiers `.env`, `.netrc`, `*.pem`, `*.key`, `id_*`… Les liens symboliques sont suivis avant la vérification. Supprimer, c'est mettre à la corbeille.

## Le contrôle du PC

Désactivé par défaut. Tant qu'il l'est, les outils du PC (applications, déplacer ou copier des fichiers, lire l'écran) ne sont pas proposés au modèle et la porte les refuse, même appelés directement. L'activer passe par une confirmation dans Réglages ; l'activer, le désactiver ou choisir la lecture de l'écran en ligne est écrit au journal (niveau 3, par toi).

- **Ouvrir** : `gtk-launch -- <identifiant>`, comme le menu d'Ubuntu ; jamais de shell, jamais la commande `Exec` interprétée par Jarvis. Ouvrir est une action : un plan à valider.
- **Fermer** : SIGTERM (l'application peut demander d'enregistrer), seulement à tes processus, et jamais à la session, à un shell, à Python, à Jarvis ni à un lanceur partagé (`flatpak`, `snap`). Si d'autres entrées du menu partagent le programme (Chrome et ses applis web), l'écran de validation le dit.
- **L'écran** : la capture passe par le portail du bureau sous Wayland ; le fichier écrit par le portail est effacé dès qu'il est lu ; rien n'est gardé ni écrit dans les traces. Par défaut, elle est lue **en local** (Ollama) : aucun filtre ne sait masquer un secret affiché dans une image, et les offres gratuites en ligne peuvent garder ce qu'on leur envoie. « En ligne » (OpenRouter) est un choix explicite ; la description qui revient est une donnée encadrée, et ses secrets connus sont masqués avant d'aller au modèle principal.
- **Les fichiers** : déplacer, copier et créer suivent les règles des fichiers ci-dessus (dossier personnel seulement, dossiers sensibles refusés) ; ce sont des actions à valider.

## Le code

Le code lancé par Jarvis tourne dans Docker (`python:3.12-alpine`) : sans réseau, système en lecture seule, utilisateur sans droits, 1 processeur, 256 Mo, 64 processus, durée bornée, conteneur toujours supprimé. Sans Docker : bubblewrap, sans réseau, avec des limites posées par `prlimit`.

## Les automatisations

Une automatisation n'a que les outils de lecture. S'il faut agir, elle prépare un plan qui t'attend, et tu es prévenu (bureau, Telegram) : elle ne déclenche jamais seule une action de niveau 2 ou 3. La créer ou la modifier est une action (niveau 2), la supprimer une destruction (niveau 3) ; depuis l'écran Automatisations, ces changements sont aussi écrits au journal. Ce qu'une automatisation provoque ne déclenche pas d'autre automatisation, et une même automatisation ne part pas plus d'une fois par minute.

## Telegram

Seul l'identifiant `TELEGRAM_ALLOWED_USER_ID` est servi ; tout autre expéditeur est ignoré et journalisé (`telegram.rejected`). Un plan de niveau 2 se valide par un bouton, et la décision est journalisée avec son canal ; un plan de niveau 3 ne se valide jamais depuis Telegram, même par un clic forgé. Le jeton du bot fait partie de l'adresse de l'API : aucune erreur ni aucun log ne la reprend.

## Les intégrations (MCP)

GitHub et Notion tournent dans des conteneurs sans privilèges, sans accès à tes fichiers, avec des versions épinglées ; leur jeton passe par l'environnement du seul serveur. Le niveau de chaque outil vient de ses annotations MCP (lecture seule → 1, destructeur → 3, sinon 2) ; un outil inconnu est traité comme une action. Les arguments sont vérifiés par le schéma de l'outil avant l'appel ; les résultats sont des données, jamais des instructions.

Google Agenda : connexion OAuth avec PKCE et état vérifié, par une redirection vers `127.0.0.1` ouverte 10 minutes au plus ; le jeton durable va au trousseau, jamais à l'interface ni au modèle ; « Déconnecter » le révoque.

## Le journal des actions

Table en ajout seul : des déclencheurs SQLite refusent toute modification et toute suppression. Chaque entrée contient l'empreinte SHA-256 de la précédente : modifier une ligne, même directement dans la base, casse la chaîne. Elle est vérifiée à chaque démarrage et à la demande (Journal et traces → Actions). Aucune route ni aucun écran ne permet de l'effacer.

## Les secrets

Clés dans le trousseau du système, jamais renvoyées à l'interface. Avant tout appel à un modèle, chaque valeur du trousseau et chaque format de clé connu est remplacé par `***`, y compris dans les résultats d'outils. Les logs et le journal sont filtrés de la même façon.
