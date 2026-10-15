# 04 — Jarvis s'organise

## Ce qui a été construit

- **Les automatisations** (`engine/src/ojarvis/automations/`) : un déclencheur (une heure, ou un événement du moteur) et une action (un rappel, ou une tâche que Jarvis fait seul). Créées depuis le chat ou la voix (« tous les matins à 8 h »), ou depuis l'écran Automatisations, où tout se modifie, se désactive, se lance ou se supprime.
- **Le moteur de workflows** (`workflows/`) : une chaîne de tâches enregistrée étape par étape ; après un plantage ou un redémarrage du PC, elle reprend où elle s'était arrêtée.
- **Le planificateur** : il dort jusqu'à la prochaine échéance, écoute le bus d'événements pour les déclencheurs « quand… », rattrape une échéance manquée de moins de 6 h.
- **Telegram** (`telegram/`) : texte et messages vocaux depuis ton téléphone ; boutons « Valider » et « Refuser » pour les plans de niveau 2.
- **Les intégrations MCP** (`integrations/`) : serveurs officiels de GitHub et de Notion, Google Agenda (serveur officiel de Google, ou celui de Jarvis).
- **Le briefing du matin** (`briefing/`) : à la première ouverture de l'app dans la journée.
- **Les notifications** : rappels et résultats arrivent dans l'app, sur le bureau et sur Telegram.

## Le trajet d'une automatisation

« Tous les jours à 8 h, résume-moi les nouvelles de la tech » :

1. Le modèle propose `creer_automatisation` : c'est une action (niveau 2), donc un plan. Tu valides.
2. L'horaire est calculé en heure locale (8 h à Paris), puis rangé en UTC.
3. À 8 h, le planificateur lance un workflow de deux étapes : la consigne, puis la notification.
4. La consigne est un tour de conversation où Jarvis travaille seul : il lit et cherche librement ; s'il faut agir, il prépare un plan, qui t'attend.
5. La notification t'arrive dans l'app et sur Telegram, avec les boutons si un plan attend.

## Les décisions qui comptent

**L'heure locale, rangée en UTC.** « 8 h » doit rester 8 h quand on passe à l'heure d'été ou d'hiver. La prochaine échéance est donc calculée dans le fuseau du système, puis convertie. Les tests couvrent les deux nuits de 2026 : en mars, 2 h 30 n'existe pas (l'automatisation tourne à 3 h 30) ; en octobre, 2 h 30 existe deux fois (elle ne tourne qu'une fois).

**Une automatisation n'agit jamais seule.** Elle n'a que les outils de lecture ; une action devient un plan, qui t'attend, et tu en es prévenu (bureau, Telegram). C'est la règle du brief, et la porte des permissions la garantit : aucune validation n'existe sans toi.

**Pas de réaction en chaîne.** Tout ce que fait une automatisation porte une marque (son identifiant de corrélation) : un événement qu'elle provoque ne peut pas en déclencher une autre. Et une même automatisation ne part pas plus d'une fois par minute.

**Deux outils pour toutes les intégrations.** GitHub expose 48 outils, Notion 24 : les montrer tous au modèle à chaque message coûterait cher et ralentirait la voix. Le modèle regarde d'abord ce que propose une intégration, puis appelle l'outil voulu. Le niveau vient des annotations MCP du serveur : lecture seule → niveau 1 ; destructeur → 3 ; sinon 2.

**Les serveurs officiels, en conteneur, versions épinglées.** GitHub (`v1.12.2`) et Notion (`2.5.2`) tournent dans Docker, sans privilèges ni accès à tes fichiers ; on a choisi des versions vieilles de quelques semaines plutôt que la toute dernière.

**Google Agenda : le serveur de Google, sinon celui de Jarvis.** Google publie un serveur MCP officiel, encore en préversion, qu'il faut activer dans ton projet Google Cloud. S'il ne répond pas, Jarvis utilise son propre petit serveur MCP (trois outils : lister, créer, supprimer un événement).

**Telegram ne valide jamais une destruction.** Même un clic forgé est refusé : la double confirmation n'existe que dans l'app.

## Ce que les tests ont attrapé

- **Un test du titre de conversation** a échoué une fois en CI : pendant une coupure du flux d'événements, l'interface rate des événements et reste figée. Elle relit maintenant tout à chaque reconnexion, et la CI garde les traces quand un test de bout en bout échoue.
- **Le volume de cache de Notion** était créé par Docker avec un propriétaire root : le serveur ne démarrait pas. Le volume couvre maintenant tout le dossier de l'utilisateur du conteneur, dont il reprend les droits.
- **Le schéma des outils MCP** a fait corriger seul au modèle un argument faux (`'open'` au lieu de `'OPEN'`) : l'erreur est renvoyée avant l'appel.

## Vérifié

- **Une automatisation survit à un redémarrage** : arrêtée avec une échéance passée depuis 10 minutes, elle est rattrapée au redémarrage, son horaire conservé ; un workflow coupé au milieu reprend à l'étape interrompue sans refaire les précédentes.
- **Le briefing se joue à la première session du jour**, une seule fois ; le lendemain, il revient ; désactivé, il se tait (réécoutable à la demande).
- **Un message Telegram est traité** (API simulée) : texte, message vocal transcrit, plan validé par bouton (journalisé avec son canal), destruction refusée, inconnu ignoré et journalisé. Le vrai bot répond (`getMe`) ; le message depuis ton téléphone est dans la checklist.
- Vrais serveurs MCP : GitHub (48 outils, ton compte reconnu), Notion (24 outils).
- Vrai DeepSeek : « tous les matins à 8 h » et « demain à 9 h » donnent le bon horaire ; issues d'un dépôt public lues par MCP ; briefing composé avec les vraies données GitHub.
- Moteur : 512 tests, couverture 91 %. Interface : 48 tests. Bout en bout : 16 scénarios.
