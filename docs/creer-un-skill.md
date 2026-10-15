# Créer un skill

Un skill donne à Jarvis une capacité durable : des fonctions Python, testées, qu'il appelle comme ses autres outils. Il peut se l'écrire lui-même ; tu peux aussi lui dicter précisément ce que tu veux.

## Ce qu'un skill peut faire, et ce qu'il ne peut pas

Un skill fait du **calcul** : il transforme ce qu'on lui donne (dates, unités, textes, nombres, formats). Son code tourne dans le bac à sable : **ni Internet, ni tes fichiers, ni tes clés**, 10 secondes et 256 Mo par appel. C'est pour ça que ses outils tournent sans te demander (niveau 1) : ils ne peuvent rien abîmer ni rien faire fuir.

Besoin d'Internet ou d'un service ? C'est le rôle d'un serveur MCP (Skills et plugins → Serveurs MCP).

## Le demander à Jarvis

> Crée-toi un skill qui convertit une durée en minutes (« 1 h 30 » → 90), avec ses tests.

Jarvis écrit le skill, lance ses tests dans le bac à sable, puis te propose de l'activer. Avant de confirmer (deux fois), regarde dans **Skills et plugins** : le code, les tests et leur résultat, les outils et leurs arguments.

## Ce qu'il contient

| Champ | Exemple | Règle |
|---|---|---|
| `nom` | `duree-en-minutes` | minuscules, chiffres, tirets ; 3 à 30 caractères |
| `version` | `1.0.0` | une version activée ne change plus : on en crée une plus haute |
| `description` | « Convertit une durée écrite en minutes. » | à quoi il sert |
| `instructions` | « Pour toute durée écrite en heures et minutes. » | quand l'utiliser (facultatif) |
| `outils` | `convertir` + schéma JSON de ses arguments | 1 à 8 fonctions, chacune décrite |
| `code` | le module Python | bibliothèque standard seulement |
| `tests` | des fonctions `test_…` avec des `assert` | au moins une ; elles voient les fonctions du code |

Exemple complet :

```python
# code
import re

def convertir(duree: str) -> int:
    """« 1 h 30 » → 90 ; « 45 min » → 45."""
    heures = re.search(r"(\d+)\s*h", duree)
    minutes = re.search(r"h\s*(\d+)", duree) or re.search(r"(\d+)\s*min", duree)
    total = int(heures.group(1)) * 60 if heures else 0
    return total + (int(minutes.group(1)) if minutes else 0)
```

```python
# tests
def test_heures_et_minutes():
    assert convertir("1 h 30") == 90

def test_minutes_seules():
    assert convertir("45 min") == 45
```

Schéma de l'outil `convertir` :

```json
{"type": "object", "properties": {"duree": {"type": "string"}}, "required": ["duree"]}
```

## Le cycle de vie

1. **Brouillon** : enregistré, ses tests tournent dans le bac à sable.
2. **Prêt à activer** (tests réussis) ou **Tests en échec** (on ne peut pas l'activer : Jarvis corrige et recrée la même version tant qu'elle n'a jamais servi).
3. **Actif** : ses outils sont disponibles (`duree_en_minutes__convertir`). Activer est une extension : double confirmation, écrite au journal des actions.
4. **Désactivé** : ses outils disparaissent, tout de suite. **Remplacé** : une version plus haute a été activée.

Supprimer une version (non active) demande aussi une double confirmation.

## Où c'est rangé

En base (table `skills`) : le code, les tests, le rapport des tests et une empreinte SHA-256 de l'ensemble. L'empreinte de la version activée est écrite au journal : on sait exactement quel code tourne.
