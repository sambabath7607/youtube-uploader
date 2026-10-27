from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import CleApi, empreinte


class CleApiAuthentication(TokenAuthentication):
    """Même en-tête qu'avant (« Authorization: Token SA_CLE »), mais la clé est cherchée par son empreinte."""

    def authenticate_credentials(self, cle):
        ligne = CleApi.objects.select_related("user").filter(empreinte=empreinte(cle)).first()
        if ligne is None or not ligne.user.is_active:
            raise AuthenticationFailed("Clé d'API non valide.")
        return (ligne.user, None)
