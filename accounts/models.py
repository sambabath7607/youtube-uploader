import hashlib
import secrets

from django.conf import settings
from django.db import models


def empreinte(cle):
    return hashlib.sha256(cle.encode()).hexdigest()


class CleApi(models.Model):
    """Clé d'API d'un utilisateur : seule l'empreinte est gardée, jamais la clé elle-même."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cle_api")
    empreinte = models.CharField(max_length=64, unique=True)
    debut = models.CharField(max_length=8)  # les 8 premiers caractères, pour reconnaître la clé sur la page
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Clé d'API de {self.user} ({self.debut}…)"

    @classmethod
    def creer_pour(cls, user):
        """Remplace la clé de l'utilisateur et renvoie la nouvelle clé en clair (à montrer une seule fois)."""
        cle = secrets.token_hex(20)
        cls.objects.update_or_create(user=user, defaults={"empreinte": empreinte(cle), "debut": cle[:8]})
        return cle
