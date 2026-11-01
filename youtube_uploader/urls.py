from django.urls import path
from . import api, depot, oauth, views

urlpatterns = [

    path("connecter/", oauth.connecter_youtube, name="connecter_youtube"),
    path("deconnecter/", oauth.deconnecter_youtube, name="deconnecter_youtube"),
    path("oauth/callback/", oauth.oauth_callback, name="oauth_callback"),
    path("nouvelle/", views.nouvelle_video, name="nouvelle_video"),
    path("video/<int:video_id>/", views.suivi_video, name="suivi_video"),
    path("ma-voix/", views.ma_voix, name="ma_voix"),
    path("mes-videos/", views.mes_videos, name="mes_videos_site"),
    path("mes-preferences/", views.mes_preferences, name="mes_preferences"),
    path("ma-voix/ecouter/", views.ecouter_ma_voix, name="ecouter_ma_voix"),
    path("ma-voix/essai/", views.essai_ma_voix, name="essai_ma_voix"),
    path("api/v1/videos/", api.api_videos, name="api_videos"),
    path("api/v1/videos/<int:video_id>/", api.api_etat_video, name="api_etat_video"),
    path("api/v1/envois/", api.api_preparer_envoi, name="api_preparer_envoi"),
    path("depot/<str:jeton>/", depot.depot_video, name="depot_video"),
    path("api/v1/compte/", api.api_mon_compte, name="api_mon_compte"),
    path("api/v1/voix/", api.api_voix, name="api_voix"),
    path("api/v1/voix/<str:travail>/", api.api_etat_voix, name="api_etat_voix"),
]
