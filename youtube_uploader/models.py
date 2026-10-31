from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models

# Les extraits de voix sont rangés dans src/prive/ : jamais servis par le site (ni /media/, ni Nginx)
stockage_prive = FileSystemStorage(location=settings.BASE_DIR / "prive")

QUOTA_GRATUIT_SECONDES = 10 * 60   # 10 minutes d'audio par mois, offertes (option « En ligne »)


class YouTubeCredentials(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_json = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Token YouTube de {self.user}"

class Video(models.Model):
    ETATS = [
        ("en_attente", "En attente"),
        ("en_cours", "En cours"),
        ("reussi", "Réussi"),
        ("echoue", "Échoué"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    titre = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    fichier = models.FileField(upload_to="videos/")
    pour_enfants = models.BooleanField()
    contenu_ia = models.BooleanField(default=False)
    etat = models.CharField(max_length=20, choices=ETATS, default="en_attente")
    youtube_id = models.CharField(max_length=50, blank=True)
    erreur = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titre

class VoixUtilisateur(models.Model):
    MODES = [
        ("en_ligne", "En ligne (rapide, sans installation)"),
        ("pc", "Sur mon PC (gratuit, plus lent)"),
        ("aucune", "Sans voix"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="voix")
    extrait = models.FileField(storage=stockage_prive, upload_to="voix/", blank=True)
    mode = models.CharField(max_length=10, choices=MODES, default="aucune")
    consentement_le = models.DateTimeField(null=True, blank=True)   # date où il a lu la phrase de consentement
    secondes_utilisees = models.PositiveIntegerField(default=0)     # audio fabriqué ce mois-ci
    mois_du_compteur = models.DateField(null=True, blank=True)      # pour remettre le compteur à zéro chaque mois
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Voix de {self.user} ({self.get_mode_display()})"
