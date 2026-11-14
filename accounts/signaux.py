from django.db.models.signals import post_save
from django.dispatch import receiver

from youtube_uploader.models import YouTubeCredentials


@receiver(post_save, sender=YouTubeCredentials)
def compter_connexion_google(sender, instance, created, **kwargs):
    """Chaque compte qui connecte une chaîne est compté une fois (seuil de la liste d'attente)."""
    if created:
        from .models import ConnexionGoogle
        ConnexionGoogle.objects.get_or_create(user=instance.user)
