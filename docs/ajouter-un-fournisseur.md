# Ajouter un fournisseur de modèles

Jarvis parle aux modèles par des adaptateurs fins, derrière le routeur (`engine/src/ojarvis/llm/`). La plupart des fournisseurs ont une API compatible OpenAI : il suffit alors de les décrire. Exemple ici avec un fournisseur imaginaire, « Mistral ».

## 1. La clé

Dans `security/secrets.py`, ajoute sa clé au catalogue (elle apparaît dans Réglages, se range au trousseau, est masquée partout) :

```python
SecretSpec("MISTRAL_API_KEY", "Mistral", "llm", "Optionnel."),
```

Le nom doit aussi être ajouté à `.env.example` (sans valeur) : au premier lancement, l'app importe les clés de `.env` dans le trousseau.

## 2. L'adaptateur

API compatible OpenAI : une description suffit, dans `llm/providers/openai_compat.py`.

```python
MISTRAL = CompatConfig("mistral", "https://api.mistral.ai/v1")
```

Les options servent aux différences connues : `max_tokens_param` (OpenAI veut `max_completion_tokens`), `thinking_switch` (DeepSeek), `needs_key=False` et `local=True` (Ollama), `headers`, `timeout_s`.

API différente (comme Anthropic) : écris une classe qui suit le protocole `Provider` de `llm/providers/base.py` — `is_configured()`, et `stream(request, model)` qui rend des événements (`TextDelta`, `ToolCallReady`, `Usage`…) et lève une `LLMError` classée en cas d'échec (`RateLimitedError`, `AuthenticationFailedError`, `QuotaExhaustedError`…). Le routeur s'appuie sur ce classement pour basculer.

## 3. L'enregistrer

Dans `llm/providers/registry.py`, `build_providers` :

```python
"mistral": OpenAICompatibleProvider(MISTRAL, key("MISTRAL_API_KEY")),
```

Sans clé, `is_configured()` est faux : le routeur l'ignore. Il s'active tout seul dès que la clé apparaît.

## 4. Ses modèles

Dans `llm/catalog.py`, `STATIC_CATALOG` décrit chaque modèle : ce qu'il sait faire (outils, vision, mode JSON), sa fenêtre de contexte et son prix (pour le coût des traces).

```python
ModelSpec(
    "mistral",
    "mistral-medium-3",
    "Mistral Medium 3",
    vision=True,
    context=128_000,
    price=Price(input=0.4, output=2.0),
),
```

## 5. Quand l'utiliser

Le routeur choisit selon la politique par tâche (`DEFAULT_POLICY` dans `llm/router.py`) : une liste ordonnée de routes, la première disponible gagne, les suivantes servent de repli. Ajoute la tienne là où elle a du sens (par exemple en repli du chat). Dans Réglages → Modèles, l'utilisateur peut aussi imposer un modèle par tâche.

Rappels qui ne changent pas : une demande sensible ou hors ligne ne part qu'en local (Ollama) ; avant tout appel, les secrets connus sont masqués.

## 6. Vérifier la clé

Dans `providers/checks.py`, une vérification légère (lister les modèles, par exemple) rend « Vérifiée » dans Réglages :

```python
async def check_mistral(client: httpx.AsyncClient, get: Getter) -> CheckResult:
    key = get("MISTRAL_API_KEY") or ""
    response = await _bearer_get(client, "https://api.mistral.ai/v1/models", key)
    if response.status_code != 200:
        return CheckResult(False, _status_detail(response))
    return CheckResult(True, "Clé valide.")
```

puis `CHECKS["MISTRAL_API_KEY"] = check_mistral`.

## 7. Les tests

Sans réseau : les tests de contrat de `tests/llm/test_providers.py` simulent l'API (requête envoyée, flux de réponse, erreurs classées). Ajoute ceux propres au fournisseur (nom du paramètre de longueur, en-têtes…), puis lance `uv run pytest tests/llm`. Avec la vraie clé, un tour réel par le banc d'essai (`engine/tools/agent_bench.py`) confirme l'appel d'outils.
