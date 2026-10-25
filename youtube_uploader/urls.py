from django.urls import path
from . import views, oauth, api

urlpatterns = [

    path("connecter/", oauth.connecter_youtube, name="connecter_youtube"),
    path("deconnecter/", oauth.deconnecter_youtube, name="deconnecter_youtube"),
    path("oauth/callback/", oauth.oauth_callback, name="oauth_callback"),
    path("nouvelle/", views.nouvelle_video, name="nouvelle_video"),
    path("api/v1/videos/", api.api_videos, name="api_videos"),
    path("api/v1/videos/<int:video_id>/", api.api_etat_video, name="api_etat_video"),
]
