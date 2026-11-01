import hashlib
import secrets

from django.conf import settings
from django.db import models


def empreinte(cle):
    return hashlib.sha256(cle.encode()).hexdigest()


class CleApi(models.Model):
    """Clé d'API d'un utilisateur : seule l'empreinte est gardée, jamais la clé elle-même."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cles_api")
    nom = models.CharField(max_length=50, default="Ma clé")   # ex. « claude.ai », « PC du bureau », « Cursor »
    empreinte = models.CharField(max_length=64, unique=True)
    debut = models.CharField(max_length=8)  # les 8 premiers caractères, pour reconnaître la clé sur la page
    created_at = models.DateTimeField(auto_now_add=True)
    dernier_usage = models.DateTimeField(null=True, blank=True)

    MAX_PAR_COMPTE = 10

    def __str__(self):
        return f"Clé « {self.nom} » de {self.user} ({self.debut}…)"

    @classmethod
    def creer_pour(cls, user, nom="Ma clé"):
        """Ajoute une clé (les autres restent valables) et la renvoie en clair : à montrer une seule fois."""
        cle = secrets.token_hex(20)
        cls.objects.create(user=user, nom=(nom or "Ma clé")[:50], empreinte=empreinte(cle), debut=cle[:8])
        return cle


# ---------- Connexion en un clic (OAuth 2.1) pour les agents IA : Claude, ChatGPT, Cursor… ----------

class ClientOAuth(models.Model):
    """Un agent IA (application cliente) enregistré automatiquement (RFC 7591) ou par son adresse (CIMD)."""
    client_id = models.CharField(max_length=300, unique=True)
    nom = models.CharField(max_length=100, blank=True)
    redirect_uris = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nom or self.client_id


class CodeOAuth(models.Model):
    """Code d'autorisation : valable 10 minutes, une seule fois, lié au PKCE (S256)."""
    empreinte = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(ClientOAuth, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    redirect_uri = models.TextField()
    code_challenge = models.CharField(max_length=128)
    resource = models.TextField(blank=True)
    expire_le = models.DateTimeField()
    utilise = models.BooleanField(default=False)


class JetonOAuth(models.Model):
    """Jeton d'accès (1 h) et jeton de rafraîchissement (30 jours, renouvelé à chaque usage) : seules les empreintes
    sont gardées, comme pour les clés d'API."""
    client = models.ForeignKey(ClientOAuth, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jetons_oauth")
    empreinte_acces = models.CharField(max_length=64, unique=True)
    empreinte_rafraichissement = models.CharField(max_length=64, unique=True)
    resource = models.TextField(blank=True)
    acces_expire_le = models.DateTimeField()
    rafraichissement_expire_le = models.DateTimeField()
    revoque = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
