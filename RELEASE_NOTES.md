# O-jarvis 1.0.0 — notes de version

O-jarvis est un assistant personnel pour Ubuntu, en français : on lui parle (« Hey Jarvis »), il se souvient, agit sous ton contrôle et sait s'étendre. Tout ce que décrit le brief est présent :

- **Parler** : sphère animée, conversation en flux, voix complète (réveil local, transcription, voix naturelle avec relais local, interruption), mémoire visible et modifiable, moteur de contexte, routeur de modèles (DeepSeek, OpenRouter, Ollama, OpenAI, Anthropic).
- **Agir** : outils à trois niveaux de permission derrière une seule porte, plans validés, journal immuable chaîné, navigateur de Jarvis, recherche web, code en bac à sable, défenses contre l'injection.
- **S'organiser** : automatisations (heure locale ou événement), workflows qui reprennent après un arrêt, Telegram, GitHub, Notion, Google Agenda, briefing du matin.
- **Contrôler le PC** (désactivé par défaut) : applications, fichiers, « regarde mon écran ».
- **S'étendre** : skills écrits et testés par Jarvis, serveurs MCP du registre officiel, agents dev, recherche et coach, mémoire graphe, suggestions avec score de confiance.
- **Installer** : paquets `.deb` et AppImage avec le moteur embarqué, démarrage automatique à l'ouverture de session (désactivable).

## Ce qui est vérifié

Chaque phase a passé sa boucle de vérification (lint, typage, tests, bout en bout avec audit d'accessibilité, audits de dépendances, revue de sécurité) ; le détail daté est dans [`PROGRESS.md`](./PROGRESS.md) et dans [`docs/journal/`](./docs/journal/README.md). Quelques repères :

- Réponse parlée : 1,75 à 1,9 s entre la fin de ta phrase et le début de la voix (médiane, vrai pipeline).
- Plans et pages piégées testés avec le vrai modèle : aucune action sans validation.
- Une automatisation survit à un redémarrage ; « 8 h » reste 8 h aux changements d'heure.
- Une application s'ouvre après validation ; « regarde mon écran » lit juste une capture de test.
- Jarvis crée un skill, le teste, demande, puis l'utilise ; un serveur MCP installé depuis le registre fonctionne.
- L'app du `.deb` dans une session neuve (dossier personnel, trousseau, affichage et son neufs) : premier lancement, conversation, briefing, « Hey Jarvis » de bout en bout, démarrage automatique, arrêt propre. Détail : [`docs/journal/07-release.md`](./docs/journal/07-release.md).

## Limites connues

- **Systèmes** : Ubuntu 24.04 ou plus récent (glibc 2.39 au minimum, WebKitGTK 4.1) ; vérifié sur Ubuntu 26.04 seulement.
- **Taille** : `.deb` de 216 Mo, AppImage de 353 Mo ; une fois installé, le moteur pèse environ 800 Mo (Whisper, ONNX, Playwright, Piper) ; les modèles vocaux (~350 Mo) et Chromium (~170 Mo) se téléchargent au premier usage.
- **AppImage** : pas de raccourci global `Ctrl+Alt+J` (le portail du bureau ne trouve pas son lanceur, que seul le `.deb` installe).
- **Transcription locale** (sans clé Groq) : la fin du mot de réveil reste parfois dans le texte (« Parvice, … ») ; la réponse reste juste.
- **Lecture d'écran locale lente** sur une machine modeste (30 s à 2 min) : c'est le prix du « rien ne sort ».
- **Offres gratuites** (OpenRouter) souvent saturées : elles ne servent que de repli.
- **Serveurs MCP sans Docker** : lancés par bubblewrap, ils gardent l'accès au réseau local.
- **Mot de réveil** prononcé avec un accent français synthétique : moins bien reconnu ; à confirmer au vrai micro (checklist).
- Ce que je n'ai pas pu vérifier moi-même (vrai micro dans la pièce, ton téléphone, installation du `.deb` par `sudo`) est dans [`docs/checklist-manuelle.md`](./docs/checklist-manuelle.md).

## La suite proposée

- Un dépôt APT ou une mise à jour automatique de l'AppImage.
- Des agents qui travaillent en parallèle sur une même demande.
- L'anticipation d'après l'agenda (préparer une réunion la veille).
- Un réveil « Hey Jarvis » entraîné sur ta voix.
