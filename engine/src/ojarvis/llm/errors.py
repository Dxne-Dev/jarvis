"""Erreurs des fournisseurs de modèles, classées pour décider d'un repli."""

from __future__ import annotations


class LLMError(Exception):
    """Base. `retryable` : un autre essai (ou un autre fournisseur) a des chances de marcher."""

    retryable = False
    #: Message court, en français, montrable à l'utilisateur.
    public = "Le modèle n'a pas pu répondre."

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class ProviderUnavailableError(LLMError):
    retryable = True
    public = "Le fournisseur ne répond pas."


class RateLimitedError(LLMError):
    retryable = True
    public = "Le fournisseur limite les requêtes pour le moment."


class AuthenticationFailedError(LLMError):
    public = "La clé du fournisseur est refusée."


class QuotaExhaustedError(LLMError):
    public = "Le crédit du fournisseur est épuisé."


class InvalidRequestError(LLMError):
    public = "Le fournisseur a refusé la requête."


class ContentRefusedError(LLMError):
    public = "Le modèle a refusé de répondre."


class NotConfiguredError(LLMError):
    public = "Aucune clé n'est enregistrée pour ce fournisseur."


class NoRouteAvailableError(LLMError):
    public = "Aucun modèle n'est disponible pour le moment."


class StructuredOutputError(LLMError):
    public = "Le modèle n'a pas produit une réponse exploitable."


def error_for_status(status: int, text: str, provider: str) -> LLMError:
    """Erreur classée d'après un code HTTP renvoyé par le fournisseur."""
    if status == 402:
        return QuotaExhaustedError(text, provider=provider)
    if status == 429:
        return RateLimitedError(text, provider=provider)
    if status in (401, 403):
        return AuthenticationFailedError(text, provider=provider)
    if status >= 500:
        return ProviderUnavailableError(text, provider=provider)
    return InvalidRequestError(text, provider=provider)
