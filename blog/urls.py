from django.contrib import admin
from django.urls import path, include

from accounts import oauth_serveur

urlpatterns = [
    path("admin/", admin.site.urls),
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


