import hashlib
import secrets

from django.conf import settings
from django.contrib.auth.models import User
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


# ---------- Liste d'attente tant que l'application Google n'est pas vérifiée (100 utilisateurs à vie) ----------

class ConnexionGoogle(models.Model):
    """Un compte qui a connecté une chaîne au moins une fois : Google le compte à vie, même après déconnexion.
    Si le compte est supprimé, la ligne reste sans aucune donnée personnelle (user vide) pour garder le bon total."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="connexion_google")
    created_at = models.DateTimeField(auto_now_add=True)


class ListeAttente(models.Model):
    """Personne qui attend une place pour connecter sa chaîne ; effacée avec son compte."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="liste_attente")
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "inscription en liste d'attente"
        verbose_name_plural = "liste d'attente"

    def __str__(self):
        return f"{self.user} ({self.email})"


# ---------- Offres Gratuit / Pro (lot 4) : le paiement se fait sur le site vitrine, qui prévient le service par le pont ----------

class Abonnement(models.Model):
    """Offre du compte. Pas de ligne = offre Gratuit. Mis à jour seulement par le pont signé du site vitrine
    (ou à la main par l'administrateur)."""
    OFFRES = [("gratuit", "Gratuit"), ("pro", "Pro")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="abonnement")
    email = models.EmailField(blank=True)                        # courriel reçu du site vitrine
    offre = models.CharField(max_length=10, choices=OFFRES, default="gratuit")
    actif = models.BooleanField(default=False)                   # paiement actif ou en essai sur le site vitrine
    fin_periode = models.DateTimeField(null=True, blank=True)    # fin de la période payée (renouvellement ou fin)
    statut_vitrine = models.CharField(max_length=20, blank=True)  # active, trialing, past_due, canceled…
    reference = models.CharField(max_length=100, blank=True)     # numéro de l'abonnement sur le site vitrine
    dernier_evenement = models.CharField(max_length=100, blank=True)
    etat_le = models.DateTimeField(null=True, blank=True)        # date de l'état reçu : un état plus ancien est ignoré
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "abonnement"

    def __str__(self):
        return f"{self.user} : {self.get_offre_display()}"

    @property
    def est_pro(self):
        return self.offre == "pro" and self.actif


class EvenementPont(models.Model):
    """Chaque appel du pont déjà traité : le même événement reçu deux fois n'a d'effet qu'une seule fois."""
    identifiant = models.CharField(max_length=100, unique=True)
    recu_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "événement du pont"
        verbose_name_plural = "événements du pont"


class CoutClient(User):
    """Vue de l'administration « Coûts par client » (aucune table : simple vue sur les comptes)."""

    class Meta:
        proxy = True
        verbose_name = "coût par client"
        verbose_name_plural = "coûts par client (ce mois-ci)"
