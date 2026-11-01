from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import CleApi, JetonOAuth, empreinte


class CleApiAuthentication(TokenAuthentication):
    """Même en-tête qu'avant (« Authorization: Token SA_CLE »), mais la clé est cherchée par son empreinte."""

    def authenticate_credentials(self, cle):
        ligne = CleApi.objects.select_related("user").filter(empreinte=empreinte(cle)).first()
        if ligne is None or not ligne.user.is_active:
            raise AuthenticationFailed("Clé d'API non valide.")
        # Date du dernier usage (affichée sur « Mes clés ») : écrite au plus une fois par heure
        maintenant = timezone.now()
        if ligne.dernier_usage is None or maintenant - ligne.dernier_usage > timedelta(hours=1):
            CleApi.objects.filter(id=ligne.id).update(dernier_usage=maintenant)
        return (ligne.user, None)



class JetonOAuthAuthentication(TokenAuthentication):
    """Jeton reçu par un agent IA après « Autoriser » (connexion en un clic) : « Authorization: Bearer JETON »."""
    keyword = "Bearer"

    def authenticate_credentials(self, jeton):
        ligne = (JetonOAuth.objects.select_related("user")
                 .filter(empreinte_acces=empreinte(jeton), revoque=False, acces_expire_le__gt=timezone.now()).first())
        if ligne is None or not ligne.user.is_active:
            raise AuthenticationFailed("Jeton d'accès invalide ou expiré.")
        return (ligne.user, None)


AUTHENTIFICATIONS = [CleApiAuthentication, JetonOAuthAuthentication]
