# 08 — La suite de scénarios

## Ce qui a été construit

- **43 scénarios en cinq niveaux** (`engine/tools/scenarios.py`), joués avec le vrai modèle : des fondamentaux (une question pleine de fautes, une demande floue, ne rien inventer) aux scénarios réels (réparer un petit projet Python, une synthèse sourcée, organiser une semaine). Le détail et le dernier tableau sont dans [`docs/scenarios.md`](../scenarios.md).
- **Chaque scénario vérifie lui-même son résultat** (le fichier contient-il « 1960 » ? le rappel est-il à 9 h demain ?), mesure sa durée et son coût, et **échoue si un plan de niveau 2 ou 3 s'exécute sans la validation qu'il a donnée**.
- **Un Jarvis neuf par scénario**, dans son propre processus, avec 2 Go de mémoire au plus.

## Ce que la suite a attrapé, et ce qui a changé dans Jarvis

- **Il croyait un fichier perdu.** Les outils lui montraient le chemin complet (`/tmp/…` pendant les tests, `/home/<ton nom>/…` en vrai). Ils lui montrent maintenant `~/notes/a.txt` : plus clair, et ton nom d'utilisateur ne part plus vers le modèle.
- **Il demandait « tu confirmes ? »** avant de proposer un plan, alors que le plan est déjà la demande de confirmation. Sa règle le dit maintenant. Ce qu'il peut lire lui-même (un identifiant, le contenu d'un fichier), il le lit d'abord.
- **Il annonçait parfois un plan sans l'avoir proposé** (« valide-le à l'écran », « confirme à l'écran »), et une fois il a même *écrit* l'appel de l'outil dans sa réponse (`<proposer_un_plan>…`) au lieu de le faire : tu aurais cherché en vain quoi valider. Le moteur repère ces formules dans toute la réponse et le relance une fois pour qu'il propose vraiment le plan ; cette relance n'est jamais enregistrée dans la conversation.
- **Une course de vitesse** : un plan était dit « fini » une fraction de seconde avant que son compte rendu entre dans la conversation. Une question posée aussitôt ne le voyait pas, et Jarvis croyait le rappel pas encore créé. L'ordre est inversé.
- **« Supprime ce rappel »** l'obligeait à retrouver un identifiant qu'il n'avait jamais vu : l'identifiant est maintenant donné dès la création.
- **« Ton dossier personnel »**, dans la description de ses outils, désignait pour lui *son* dossier (« mon dossier, pas forcément le tien »). Sa règle précise que c'est le tien.
- **Une demande en partie impossible** (« crée un projet React et installe ses dépendances ») le bloquait : il posait trois questions. Il écrit maintenant le projet après ta validation et dit ce qui reste (`npm install`).
- **Un plan s'arrêtait sur un dossier pas encore créé** : pour le projet React, Jarvis commençait parfois par « lister `~/projets/todo` », l'étape échouait (dossier introuvable) et tout le plan s'arrêtait. Lister un dossier absent répond maintenant « ce dossier n'existe pas encore ».
- **Il croyait que le contrôle du PC lui donnerait un terminal** : faux, et sa règle le dit. C'est le futur mode shell ([issue #7](https://github.com/octavebahoun/O-jarvis/issues/7)).

## Ce que la suite a coûté

**Un gel de ton ordinateur** (16/10, vers 5 h 30) : la première version lançait 41 Jarvis dans un même processus sans rendre leur mémoire, jusqu'à 5,8 Go. Linux a fini par couper ce processus. D'où un processus par scénario, plafonné à 2 Go par `systemd-run` : au-delà, seul ce scénario s'arrête.

## Vérifié

- Dernière série complète : **41 réussis sur 42 joués** (le 43ᵉ agit sur ton bureau et ne se joue qu'à la demande), en 9 min pour 0,07 $, sans aucune action de niveau 2 ou 3 exécutée sans validation. Les ratés changent d'une série à l'autre (de 39 à 41 sur 42) : un modèle ne répond jamais deux fois pareil.
- Moteur : ruff, mypy strict, 569 tests (nouveaux : chemins en `~/`, plan annoncé puis proposé, formules et faux appel repérés, une seule relance).
