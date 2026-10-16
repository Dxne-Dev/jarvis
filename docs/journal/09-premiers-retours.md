# 09 — Tes premiers retours d'usage

## Ce que tu as vu

- Jarvis a bien écrit le rapport demandé dans `~/Téléchargements`, puis son compte rendu a mis en doute ses propres outils (« ça peut être une simulation »). À la question suivante, il a **nié avoir créé le fichier**, avant de s'excuser.
- Ce compte rendu s'affichait **deux fois** dans la conversation.
- La capture d'écran a été refusée, et Jarvis a inventé un réglage « Accès à l'écran » qui n'existe pas.
- Tes **messages vocaux Telegram** n'étaient pas transcrits, alors que ta clé Groq était bien dans le `.env`.
- Il ne sait pas **montrer une image** (une capture, par exemple) : c'est l'[issue #31](https://github.com/octavebahoun/O-jarvis/issues/31).

## Pourquoi, et ce qui a changé

- **Le compte rendu d'un plan** était rédigé à partir d'un message « Ma demande : … », qui ne contenait que ta dernière phrase (« je viens d'activer le contrôle du PC »). Le modèle a cru te répondre, sans savoir que les résultats venaient de ses propres outils. Ils lui sont maintenant présentés comme tels, réels : une étape « faite » ne se met pas en doute, et il ne salue pas.
- **À chaque tour, Jarvis lit l'état réel des plans de la conversation** (exécuté, refusé, en attente) au lieu de se fier à sa mémoire de l'échange : il ne peut plus nier ce qui a été fait.
- **Dans la conversation**, la carte du plan ne répète plus le compte rendu : il suit en message. L'écran des actions, lui, le garde.
- **Le refus de capture** dit qu'il vient de GNOME, pas de Jarvis, et où l'autoriser ; depuis Telegram, il faut l'avoir accepté une fois devant le PC.
- **Les vocaux Telegram** : ton app tourne avec le lanceur, qui ne lisait que `~/.config/o-jarvis/.env`. La clé Groq, ajoutée au `.env` du dépôt après les premiers lancements, n'était donc jamais arrivée au trousseau. Quand la coque lance le moteur depuis les sources, elle lui indique maintenant le `.env` du dépôt : les clés manquantes rejoignent le trousseau au démarrage suivant. Et un vocal sans clé dit où l'ajouter (Réglages, « Fournisseurs et clés »), en le notant dans les journaux.

## Vérifié

- Nouveau scénario « Assumer ce qu'il a fait » (ton cas, contrôle du PC activé) : réussi dans la dernière série complète (**43 sur 43**). Sur trois essais isolés : deux réussites ; la troisième fois, Jarvis a écrit le rapport dans la conversation au lieu de proposer un plan, puis a honnêtement dit que rien n'était créé.
- Moteur : 571 tests ; interface : 68 tests ; coque : 9 tests (dont la lecture du `.env` du dépôt).
