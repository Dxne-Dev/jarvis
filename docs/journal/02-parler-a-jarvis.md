# 02 — Parler à Jarvis

## Ce qui a été construit

- **Le routeur de modèles** (`engine/src/ojarvis/llm/`) : DeepSeek, OpenRouter, OpenAI, Anthropic, Ollama et un modèle de test, derrière une même interface. Il choisit selon la tâche, bascule si un fournisseur tombe et le signale à l'interface. Dans Réglages, on peut imposer un modèle par type de tâche.
- **La conversation** : réponses en flux, markdown, historique cherchable, nouvelle conversation, coût et latence sous chaque réponse.
- **La mémoire** : faits, préférences et profil, que l'on voit, corrige et supprime dans l'écran Mémoire ; recherche par le sens (embeddings locaux) et par les mots.
- **Le moteur de contexte** : pour chaque question, il choisit ce qu'il envoie au modèle (profil, souvenirs, historique) dans un budget de jetons. Le choix est visible dans la trace.
- **La voix** (`engine/src/ojarvis/voice/`) : « Hey Jarvis », écoute, transcription, réponse parlée, interruption. Le schéma est dans [`../architecture.md`](../architecture.md).
- **Le bureau** : raccourci clavier global (Ctrl+Alt+J), notifications, sous-titres de ce que dit Jarvis.

## Le trajet d'une phrase

1. Le micro envoie une trame toutes les 80 ms. openWakeWord y cherche « Hey Jarvis » (4 ms de calcul par trame).
2. Après le mot de réveil, le détecteur de parole (Silero) attend la fin de la phrase : 0,6 s de silence. Dès 0,2 s de silence, Whisper commence à transcrire, en avance.
3. Le texte part au modèle (DeepSeek). La réponse revient mot à mot ; dès qu'une phrase est complète, elle part à Cartesia.
4. Cartesia renvoie le son en flux : Jarvis parle pendant que le modèle écrit encore la suite.

Pendant tout ce temps, le micro reste écouté : on peut couper Jarvis en parlant.

## Les décisions qui comptent

**Un mot de réveil anglais, un utilisateur francophone.** Le modèle `hey_jarvis` a appris l'anglais : dit « à la française », « Jarvis » obtient un score moyen. Quand le score hésite, les deux dernières secondes sont transcrites en local, et l'on cherche « Jarvis » dans le texte, même écorché (« Jarvi », « Jervus »). Rien ne quitte la machine.

**Whisper sur 10 secondes au lieu de 30.** Whisper encode toujours 30 s d'audio, même pour une phrase de 2 s. En réduisant cette fenêtre, la transcription passe de 1,7 s à 0,45 s sur ce processeur, pour le même texte.

**L'annulation d'écho de PipeWire.** Sans elle, Jarvis s'entend parler et se coupe lui-même. Le moteur charge le module au démarrage (sans sudo) et le retire à l'arrêt ; les réglages audio du système ne changent pas.

**Prudence avant d'apprendre.** Whisper donne une note de confiance à son texte. Si elle est basse, Jarvis répond (et demande de répéter), mais ne retient rien : une phrase mal entendue ne doit pas devenir un souvenir.

**Un délai maximal pour le premier mot.** Le 15 octobre, DeepSeek acceptait les requêtes sans jamais répondre (incident de leur côté). Le routeur abandonne maintenant un fournisseur muet après 5 s pour la voix, et passe au suivant.

## Ce que les tests ont attrapé

- Le **détecteur de réveil** gardait 1,5 s d'audio en mémoire : pendant la réponse, il réentendait le « Hey Jarvis » de départ et coupait Jarvis. Il est remis à zéro au réveil.
- **Lister les micros** réinitialisait la bibliothèque audio pendant l'écoute : le micro se taisait sans erreur. La liste vient maintenant de PipeWire, et un micro muet est détecté puis relancé.
- **L'arrêt du bus d'événements** pouvait tourner en boucle sans fin (bug de la phase 1, trouvé par les tests de la voix).
- Le **test instable** signalé en phase 1 (flux WebSocket) venait d'une annulation mal reconnue : réécrit avec un groupe de tâches anyio.
- Le banc d'essai a montré Jarvis appeler l'utilisateur « Kélela » : un faux prénom tiré d'une phrase mal transcrite. D'où le garde-fou sur la confiance.

## Le premier essai au vrai micro

Le réveil marchait, la transcription non : « Peuja mis », « Hey, Charles ! ». Deux causes :

- **Le micro était réglé à 25 %** : la voix arrivait à −36 dB, trop faible. Il est à 80 %.
- **Whisper `base` est trop petit** pour un micro intégré, à distance, avec du bruit. Sur le corpus rendu aussi faible et bruité, il se trompe sur 93 % des mots.

Décision prise ensemble : **la phrase est transcrite par Cartesia Ink-2**, en ligne, pendant qu'on parle. Sur le même corpus dégradé : 0 % d'erreurs. Le texte arrive 180 ms après la fin de la phrase. Whisper local reste en secours si le réseau tombe, et rien ne sort avant « Hey Jarvis ».

En chemin : le début d'une phrase dite juste après « Hey Jarvis » pouvait être coupé (le tampon d'avant la phrase n'était pas ajouté). Corrigé.

## Vérifié

- Corpus de 36 fichiers : « Hey Jarvis, … » dit par Piper, espeak-ng et Cartesia, plus des phrases sans mot de réveil. Réveil : 17 sur 21 (toutes les voix sauf espeak-ng à l'accent français), aucun faux réveil.
- **Latence de la fin de la phrase au premier son : médiane 1,72 s** (maximum 2,4 s) sur 12 tours réels, avec la transcription Cartesia, DeepSeek et la voix Cartesia ; 0 % d'erreurs de mots. Avec Whisper local : médiane 1,75 s. Objectif : moins de 3 s.
- **Un fait donné dans une session est rappelé dans la suivante** (vrai DeepSeek) : « Thé à la menthe », « Tu habites à Cotonou ».
- Moteur : 346 tests, couverture 91 %, ruff et mypy strict (code et tests) sans erreur, `pip-audit` sans faille.
- Interface : 36 tests ; bout en bout : 11 scénarios dont un tour vocal complet (audio simulé) ; audit axe sans violation sérieuse.
- Machine réelle : voix prête en 6 s, annulation d'écho chargée puis retirée, arrêt complet en 1 s quand l'app se ferme.

Ce qui demande un vrai micro dans la pièce est dans [`../checklist-manuelle.md`](../checklist-manuelle.md).
