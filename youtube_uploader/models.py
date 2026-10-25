from django.conf import settings
from django.db import models


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