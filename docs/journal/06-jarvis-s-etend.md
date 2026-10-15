# 06 — Jarvis s'étend

## Ce qui a été construit

- **Les skills** (`engine/src/ojarvis/skills/`) : un skill est un module versionné — description, mode d'emploi, outils (avec le schéma JSON de leurs arguments), code Python et tests. Jarvis peut s'en écrire un ; son code ne tourne que dans le bac à sable.
- **Le registre MCP** (`integrations/registry.py`, `integrations/mcp_registry.py`) : chercher un serveur dans le registre officiel, l'essayer isolé, l'installer, le désactiver, le retirer.
- **Les agents** (`agents/`) : dev, recherche et coach d'apprentissage, qui héritent tous de `BaseAgent` ; un orchestrateur sans logique métier leur confie les tâches.
- **La mémoire graphe** (`memory/graph.py`) : les personnes, projets, événements, lieux et sujets de ta vie, et ce qui les relie.
- **L'apprentissage et l'anticipation** (`anticipation/`) : des suggestions avec un score de confiance, tirées de tes demandes répétées et de tes habitudes.
- **Les écrans** : Skills et plugins, Agents, la vue Graphe dans Mémoire, les suggestions à l'Accueil.

## Le trajet d'un skill

« Crée-toi un skill qui compte les jours entre deux dates » :

1. Le modèle appelle `creer_skill` avec la description, l'outil `jours_entre` (et le schéma de ses arguments), le code et les tests.
2. Le brouillon est enregistré, puis ses tests tournent dans le bac à sable : sans Internet, sans tes fichiers, sans tes clés, en 20 s au plus.
3. Si les tests réussissent, l'activation est proposée d'elle-même : un plan de niveau 3 (« s'étendre »), avec les outils, les permissions et le résultat des tests. Tu confirmes deux fois.
4. L'outil `jours_entre_dates__jours_entre` apparaît ; à chaque appel, son code tourne dans le bac à sable et son résultat revient comme une donnée.

Une version activée ne change plus (son empreinte est gardée) : pour corriger, Jarvis écrit une version plus haute, qui remplace l'ancienne une fois activée.

## Le trajet d'un serveur MCP

1. Recherche dans le registre officiel (`registry.modelcontextprotocol.io`) : nom, version, ce que fait le serveur, où il tournerait, les réglages qu'il demande.
2. Essai : il est lancé isolé et liste ses outils avec leur niveau (lecture, action, destruction), puis arrêté.
3. Installation : double confirmation. Ses clés (s'il en demande) vont au trousseau ; ses outils rejoignent `integrations_outils` et `integration_appeler`, chacun à son niveau.

Il tourne **isolé** : dans un conteneur Docker sans privilèges, avec son propre volume ; sinon, avec bubblewrap, en lançant le `npx` ou le `uvx` de ta machine dans un espace qui ne voit ni ton dossier personnel ni tes clés.

## Les décisions qui comptent

**Un skill, c'est du calcul.** Pas d'Internet, pas de fichiers, pas de clés : il transforme ce qu'on lui donne. Ce qui demande le réseau passe par un serveur MCP, qu'on installe en connaissance de cause. Ainsi, un skill peut tourner sans te demander (niveau 1) : il ne peut rien abîmer ni rien faire fuir.

**Le code d'un skill ne tourne jamais dans le moteur.** Un petit programme d'accueil le charge dans le bac à sable ; le résultat revient sur une ligne marquée d'un jeton tiré à chaque exécution.

**L'activation se propose toute seule.** Le vrai modèle écrivait et testait bien son skill, mais oubliait d'en demander l'activation. Un outil peut maintenant proposer sa suite (`FollowUp`) : l'agent en fait un plan, au niveau de cette suite. Seul le code d'un outil peut le faire, jamais un contenu lu.

**Des clés jamais transmises par le modèle.** Si un serveur demande une clé, tu l'installes depuis l'écran, où tu la saisis toi-même ; le modèle ne la voit jamais.

**Les agents passent par le même cœur que Jarvis.** Même porte des permissions, mêmes plans, même encadrement du contenu extérieur. Chacun n'a que ses outils (un outil hors de sa liste est refusé, même glissé dans un plan) et ne voit que sa tâche, pas ta conversation. L'orchestrateur ne choisit rien : il lance, suit et rapporte.

**Le graphe naît du même appel que les faits.** L'extraction relève aussi les entités et leurs liens ; une entité par nom (comparé sans majuscules ni accents). Quand tu cites une entité connue, ses liens entrent dans le contexte, dans le budget de jetons.

**Une suggestion ne fait rien seule.** L'accepter ouvre une conversation où Jarvis s'y met ; une automatisation ou un skill passent alors par un plan que tu valides. L'anticipation ne reçoit qu'une vue en lecture de la mémoire.

## Ce que les tests ont attrapé

- **Le marqueur du résultat d'un skill disparaissait** : `str.splitlines()` coupe aussi sur le caractère `\x1e` qui le précédait. Le marqueur est maintenant en ASCII simple.
- **Un assert raté ne disait pas quelle ligne** : le code compilé depuis une chaîne n'a pas de source pour la trace ; elle est fournie à `linecache`.
- **L'essai d'un serveur MCP semblait toujours échouer** : l'état était lu après la fermeture, qui le remet à « arrêté ».
- **Après l'installation, ses outils étaient vus comme des actions** : le serveur ne démarrait qu'au premier usage, ses niveaux étaient donc inconnus. Il démarre maintenant tout de suite.
- **« Mêmes mots, autre projet »** : pour le modèle de sens (e5), « résume les issues de O-jarvis » et « … de Notion » se ressemblent à 0,96. Deux demandes ne comptent comme « la même » que si leurs noms propres sont les mêmes.
- **Un test du briefing échouait vers minuit** : son rappel « dans 5 minutes » tombait le lendemain. L'horloge du briefing est figée dans le test.

## Vérifié

- **Jarvis crée un skill, le teste, demande, puis l'utilise** (vrai DeepSeek) : skill « jours-entre-dates » écrit avec 10 tests (10/10 dans le bac à sable), activation confirmée deux fois, puis « combien de jours entre le 1er janvier et le 15 octobre 2026 ? » → 287 jours, par l'outil du skill.
- **Un serveur MCP installé depuis le registre fonctionne** (vrai registre, vrai DeepSeek) : Jarvis cherche, propose l'installation du serveur Wikipédia (`@cyanheads/wikipedia-mcp-server@0.2.6`), double confirmation, essai isolé (bubblewrap : Docker était arrêté), puis répond sur Cotonou grâce à lui.
- **Délégation à un agent** (vrai DeepSeek) : l'agent de recherche a cherché et lu seul (14 appels d'outils), puis rendu son compte rendu à Jarvis.
- Sécurité : un outil hors des attributions d'un agent est refusé ; activer ou installer exige la double confirmation (refusé sans elle, par l'API comme par un plan) ; les clés d'un serveur MCP vont au trousseau et au filtre des logs, jamais dans les réponses ; un skill ne voit ni le réseau ni tes fichiers ; la liste des outils d'un serveur est encadrée comme une donnée ; l'anticipation ne modifie pas la mémoire (vérifié ligne à ligne).
- Moteur : 558 tests. Interface : 63 tests. Bout en bout : 20 scénarios, dont agents, skills et plugins, graphe (avec audit axe).
