from django.contrib import admin
from django.urls import path, include

from accounts import oauth_serveur, pont
from accounts.views import connecter_ma_chaine
from youtube_uploader.views import sante

urlpatterns = [
    path("admin/", admin.site.urls),
    # Page de santé (lot 5) : surveillée de l'extérieur toutes les 5 min (tâche E2)
    path("sante/", sante, name="sante"),
    # « Connecter ma chaîne » passe d'abord par la liste d'attente (limite Google de 100 utilisateurs), placé avant
    # youtube_uploader.urls pour l'emporter sur /youtube/connecter/ ; {% url 'connecter_youtube' %} y mène toujours
    path("youtube/connecter/", connecter_ma_chaine),
    # Pont signé du site vitrine (offres Gratuit / Pro, lot 4) : placé ici pour ne pas toucher youtube_uploader/urls.py
    path("youtube/api/v1/interne/abonnements/", pont.recevoir_abonnement, name="pont_abonnements"),
    path("youtube/", include("youtube_uploader.urls")),
    # Connexion en un clic (OAuth) des agents IA au connecteur /mcp
    path(".well-known/oauth-authorization-server", oauth_serveur.metadonnees_serveur),
    path(".well-known/oauth-protected-resource", oauth_serveur.metadonnees_ressource),
    path(".well-known/oauth-protected-resource/mcp", oauth_serveur.metadonnees_ressource),
    path("oauth/register/", oauth_serveur.enregistrer_client, name="oauth_register"),
    path("oauth/authorize/", oauth_serveur.autoriser, name="oauth_authorize"),
    path("oauth/token/", oauth_serveur.jeton, name="oauth_token"),
    path("oauth/retirer/", oauth_serveur.retirer_acces, name="oauth_retirer"),
    path("", include("accounts.urls")),


]


