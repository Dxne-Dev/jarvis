# Contribuer à O-jarvis

Merci de vouloir améliorer Jarvis. Ce guide tient en une page : lis-le avant d'ouvrir une pull request.

## Avant de coder

- Pour un changement important (nouvel écran, nouvel outil, autre avatar…), ouvre d'abord une issue : on se met d'accord sur l'idée avant le code.
- Une pull request = un sujet. Un changement sans rapport (port, configuration, dépendance) va dans une autre PR.
- Ouvre ta PR vers la branche `dev`.

## Les règles du projet

- Jarvis tourne en local : aucun appel à un site extérieur sans raison (images, polices et scripts sont dans le dépôt).
- Les secrets ne vont jamais vers un modèle ni dans les logs ; les clés restent dans le trousseau du système.
- Toute action passe par la porte des permissions (Lire, Agir, Détruire) : on ne la contourne pas.
- Un nouveau réglage garde le comportement actuel par défaut.
- Messages de commit en français, au format Conventional Commits (`feat(app): …`, `fix(moteur): …`).

## Vérifier avant d'envoyer

La CI doit passer. En local :

```bash
cd engine && uv run ruff check src tests tools && uv run ruff format --check src tests tools
cd engine && uv run mypy src tests tools && uv run pytest -m "not real"
cd app && pnpm typecheck && pnpm lint && pnpm format:check && pnpm test
```

## Montrer le résultat

Chaque PR montre ce qu'elle change, qu'il s'agisse de l'interface ou du moteur :

- **Interface** : une capture ou une courte vidéo avant / après de chaque écran touché.
- **Moteur** : la sortie qui prouve que ça marche (réponse de Jarvis, extrait de trace du Journal, sortie d'un test ou d'une commande).
- **Nouvelle fonctionnalité** : une démonstration du parcours complet, de la demande au résultat.

**Exception, la sécurité** : pas de capture qui montrerait comment exploiter une faille. À la place, justifie le changement par écrit : le risque corrigé, pourquoi cette solution, et comment tu l'as testée. Pour une faille encore ouverte, contacte d'abord le mainteneur en privé, jamais dans une issue publique. Le modèle de sécurité de Jarvis est décrit dans [`docs/securite.md`](./docs/securite.md).
