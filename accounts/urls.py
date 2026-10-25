from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView
from . import views

urlpatterns = [
    path("inscription/", views.inscription, name="inscription"),
    path("login/", LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("ma-cle/", views.ma_cle, name="ma_cle"),
    path("mes-donnees/", views.mes_donnees, name="mes_donnees"),
    path("supprimer-compte/", views.supprimer_compte, name="supprimer_compte"),
    path("confidentialite/", views.politique_confidentialite, name="confidentialite"),
    path("conditions/", views.conditions_utilisation, name="conditions"),
    path("", views.accueil, name="accueil"),
    path("guide-api/", views.guide_api, name="guide_api"),
]
