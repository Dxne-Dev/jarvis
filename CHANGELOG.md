# Changements

Format inspiré de « Keep a Changelog ». Le détail de chaque évolution est dans [`docs/journal/`](./docs/journal/README.md).

## Non publié

### Ajouté
- Suite de 43 scénarios par niveaux (`engine/tools/scenarios.py`), joués avec le vrai modèle ; résultats dans `docs/scenarios.md`.

### Corrigé
- Jarvis ne demande plus « tu confirmes ? » avant de proposer un plan : le plan est la confirmation.
- Un plan annoncé mais jamais proposé est maintenant proposé pour de vrai.
- Les chemins que Jarvis lit commencent par `~/` : plus de confusion, et ton nom d'utilisateur ne part plus vers le modèle.
- Le compte rendu d'un plan est dans la conversation dès que le plan est fini.
- L'identifiant d'une automatisation est donné dès sa création.
- Lister un dossier qui n'existe pas encore n'arrête plus un plan.

## 1.0.0 — 16 octobre 2026

Première version complète.

### Parler à Jarvis
- Fenêtre avec la sphère animée (6 états), conversation en flux, historique cherchable, markdown.
- Voix : « Hey Jarvis » reconnu en local, transcription Groq (français imposé) avec relais, voix Cartesia ou Piper, interruption en parlant, relance sans mot de réveil, sous-titres ; réponse parlée en moins de 2 s (médiane mesurée).
- Mémoire : faits, préférences et profil visibles et modifiables ; recherche par le sens et par les mots ; moteur de contexte avec budget de jetons.
- Routeur de modèles : DeepSeek, OpenRouter, Ollama, OpenAI, Anthropic ; bascule signalée ; modèle imposé par tâche ; données sensibles en local.

### Jarvis agit
- Outils à schéma strict et trois niveaux de permission appliqués par une seule porte ; plans visibles, validés (double confirmation au niveau 3), exécutés étape par étape.
- Journal des actions immuable, chaîné par SHA-256, vérifié au démarrage.
- Navigateur de Jarvis (Playwright) derrière un proxy de garde ; sessions par domaine, chiffrées, révocables.
- Défenses contre l'injection : contenu extérieur encadré comme donnée, plans signalés, adresses fabriquées validées.

### Jarvis s'organise
- Automatisations (heure locale, changements d'heure testés, ou événement) ; workflows persistés qui reprennent après un arrêt.
- Telegram (texte et vocal), intégrations MCP officielles (GitHub, Notion, Google Agenda), briefing du matin, notifications.

### Jarvis contrôle le PC
- Désactivé par défaut : ouvrir et fermer des applications, ranger des fichiers, « regarde mon écran » (portail Wayland, lu en local par défaut).

### Jarvis s'étend
- Skills écrits par Jarvis, testés en bac à sable, activés après double confirmation.
- Registre MCP officiel : chercher, essayer isolé, installer, désactiver.
- Agents dev, recherche et coach, délégués par un orchestrateur ; mémoire graphe ; suggestions (demandes répétées, projets délaissés) avec score de confiance.

### Release
- Paquets `.deb` et AppImage, moteur Python embarqué (aucune installation de Python nécessaire).
- Démarrage automatique à l'ouverture de session (désactivable), discret dans la barre système.
- Chromium du navigateur de Jarvis téléchargé au premier usage.
- Un démarrage lent (trousseau à déverrouiller, machine chargée) n'est plus un échec : l'app se connecte dès que le moteur est prêt.
- Les bulles d'information disparaissent après 8 s et s'affichent en haut, loin de la zone de saisie.
