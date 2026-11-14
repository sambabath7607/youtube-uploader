from django.urls import path
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LogoutView
from . import views

urlpatterns = [
    path("inscription/", views.inscription, name="inscription"),
    path("login/", views.ConnexionView.as_view(), name="login"),
    # Mot de passe oublié : vues intégrées de Django (lien par courriel, valable 1 heure et une seule fois)
    path("mot-de-passe-oublie/", views.MotDePasseOublieView.as_view(), name="password_reset"),
    path("mot-de-passe-oublie/envoye/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/mot_de_passe_envoye.html"), name="password_reset_done"),
    path("nouveau-mot-de-passe/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="accounts/nouveau_mot_de_passe.html"), name="password_reset_confirm"),
    path("nouveau-mot-de-passe/termine/", auth_views.PasswordResetCompleteView.as_view(
        template_name="accounts/mot_de_passe_change.html"), name="password_reset_complete"),
    path("mon-compte/", views.mon_compte, name="mon_compte"),
    path("contact/", views.contact, name="contact"),
    path("contact/envoye/", views.contact_envoye, name="contact_envoye"),
    path("liste-attente/", views.liste_attente, name="liste_attente"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("ma-cle/", views.ma_cle, name="ma_cle"),
    path("mes-donnees/", views.mes_donnees, name="mes_donnees"),
    path("supprimer-compte/", views.supprimer_compte, name="supprimer_compte"),
    path("confidentialite/", views.politique_confidentialite, name="confidentialite"),
    path("conditions/", views.conditions_utilisation, name="conditions"),
    path("", views.accueil, name="accueil"),
    path("guide-api/", views.guide_api, name="guide_api"),
    path("guide-claude/", views.guide_claude, name="guide_claude"),
]
