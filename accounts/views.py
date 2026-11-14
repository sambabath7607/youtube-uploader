import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordResetView
from django.core.mail import EmailMessage, send_mail
from django.http import JsonResponse
from django.shortcuts import render, redirect, resolve_url
from django.urls import reverse, reverse_lazy

from youtube_uploader.models import Video, YouTubeCredentials
from youtube_uploader.oauth import connecter_youtube, revoquer_token_google
from .forms import ContactForm, CourrielForm, InscriptionForm, ListeAttenteForm
from .limites import limite_atteinte
from .models import CleApi, ConnexionGoogle, ListeAttente

journal = logging.getLogger(__name__)


def accueil(request):
    # Visiteur : page publique de présentation (Google exige une page d'accueil qui décrit le service)
    if not request.user.is_authenticated:
        from .offres import limites_affichees
        return render(request, "accounts/presentation.html", {"limites": limites_affichees(),
                                                               "pro": settings.OFFRES["pro"]})
    from youtube_uploader.models import Video, VoixUtilisateur, YouTubeCredentials
    voix = VoixUtilisateur.objects.filter(user=request.user).first()
    etapes = [
        ("Connecter ta chaîne YouTube", YouTubeCredentials.objects.filter(user=request.user).exists(), "#chaine"),
        ("Enregistrer ta voix", bool(voix and voix.extrait), "ma_voix"),
        ("Tester ta voix et choisir « C'est ma voix »", bool(voix and voix.voix_validee), "ma_voix"),
        ("Créer une clé et ajouter le connecteur dans Claude", CleApi.objects.filter(user=request.user).exists(), "guide_claude"),
        ("Publier ta première vidéo", Video.objects.filter(user=request.user, etat="reussi").exists(), "guide_claude"),
    ]
    return render(request, "accounts/accueil.html", {
        "etapes": etapes, "etapes_faites": sum(1 for _, fait, _ in etapes if fait), "nb_etapes": len(etapes),
    })


def inscription(request):
    if request.method == "POST":
        form = InscriptionForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Bienvenue ! Ton compte est créé. Connecte maintenant ta chaîne YouTube.")
            return redirect("accueil")
    else:
        form = InscriptionForm()
    return render(request, "accounts/inscription.html", {"form": form})


@login_required
def ma_cle(request):
    """Mes clés : une clé par appareil ou agent IA ; en créer une n'annule pas les autres."""
    nouvelle_cle = nom_nouvelle_cle = None
    if request.method == "POST":
        if request.POST.get("action") == "supprimer":
            CleApi.objects.filter(user=request.user, id=request.POST.get("id")).delete()
            messages.success(request, "Clé supprimée : elle ne fonctionne plus.")
            return redirect("ma_cle")
        if CleApi.objects.filter(user=request.user).count() >= CleApi.MAX_PAR_COMPTE:
            messages.error(request, f"Maximum {CleApi.MAX_PAR_COMPTE} clés : supprime d'abord une clé inutile.")
            return redirect("ma_cle")
        nom_nouvelle_cle = request.POST.get("nom", "").strip() or "Ma clé"
        nouvelle_cle = CleApi.creer_pour(request.user, nom_nouvelle_cle)
    cles = CleApi.objects.filter(user=request.user).order_by("-created_at")
    from django.db.models import Max
    from django.utils import timezone
    from .models import JetonOAuth
    agents = (JetonOAuth.objects.filter(user=request.user, revoque=False, rafraichissement_expire_le__gt=timezone.now())
              .values("client_id", "client__nom", "client__client_id").annotate(depuis=Max("created_at")))
    return render(request, "accounts/ma_cle.html",
                  {"cles": cles, "nouvelle_cle": nouvelle_cle, "nom_nouvelle_cle": nom_nouvelle_cle, "agents": agents})


def voix_exportee(user):
    from youtube_uploader.models import VoixUtilisateur
    voix = VoixUtilisateur.objects.filter(user=user).first()
    if voix is None or not voix.extrait:
        return None
    return {"mode": voix.mode, "consentement_le": voix.consentement_le.isoformat() if voix.consentement_le else None,
            "remarque": "L'extrait de voix s'écoute sur la page « Ma voix » ; il est effacé avec le compte."}


@login_required
def mes_donnees(request):
    # Export des données personnelles (sans aucun token ni secret)
    user = request.user
    donnees = {
        "nom_utilisateur": user.username,
        "email": user.email,
        "date_inscription": user.date_joined.isoformat(),
        "chaine_youtube_connectee": YouTubeCredentials.objects.filter(user=user).exists(),
        "voix": voix_exportee(user),
        "cles_api": [{"nom": c.nom, "debut": c.debut, "creee_le": c.created_at.isoformat()}
                     for c in CleApi.objects.filter(user=user)],
        "videos": [
            {
                "titre": video.titre,
                "description": video.description,
                "pour_enfants": video.pour_enfants,
                "etat": video.etat,
                "youtube_id": video.youtube_id,
                "erreur": video.erreur,
                "created_at": video.created_at.isoformat(),
            }
            for video in Video.objects.filter(user=user).order_by("created_at")
        ],
    }
    reponse = JsonResponse(donnees, json_dumps_params={"ensure_ascii": False, "indent": 2})
    reponse["Content-Disposition"] = 'attachment; filename="mes_donnees.json"'
    return reponse


@login_required
def supprimer_compte(request):
    if request.method == "POST":
        user = request.user
        if not user.check_password(request.POST.get("mot_de_passe", "")):
            return render(request, "accounts/supprimer_compte.html", {"erreur": "Mot de passe incorrect."})
        ligne = YouTubeCredentials.objects.filter(user=user).first()
        if ligne:
            revoquer_token_google(ligne)
        for video in Video.objects.filter(user=user):
            if video.fichier:
                video.fichier.delete(save=False)
        from youtube_uploader.models import VoixUtilisateur
        for voix in VoixUtilisateur.objects.filter(user=user):
            if voix.extrait:
                voix.extrait.delete(save=False)   # le fichier de voix, pas seulement la fiche
        logout(request)
        user.delete()  # supprime aussi le token Google, la clé d'API et les vidéos (CASCADE)
        messages.success(request, "Ton compte et toutes tes données ont été supprimés.")
        return redirect("login")
    return render(request, "accounts/supprimer_compte.html")


def politique_confidentialite(request):
    return render(request, "accounts/confidentialite.html")


def conditions_utilisation(request):
    return render(request, "accounts/conditions.html")


def tarifs(request):
    """Offres Gratuit / Pro : le paiement se fait sur le site vitrine (Stripe), l'accès Pro arrive tout seul ici."""
    from .offres import offre_du_compte
    offre_actuelle = offre_du_compte(request.user)[0] if request.user.is_authenticated else None
    return render(request, "accounts/tarifs.html", {
        "gratuit": settings.OFFRES["gratuit"], "pro": settings.OFFRES["pro"], "offre_actuelle": offre_actuelle,
        "url_paiement_pro": settings.URL_PAIEMENT_PRO, "url_gerer_abonnement": settings.URL_GERER_ABONNEMENT,
    })

def guide_api(request):
    from .offres import limites_affichees
    return render(request, "accounts/guide_api.html", {"limites": limites_affichees(request.user)})


def guide_claude(request):
    from .offres import limites_affichees
    return render(request, "accounts/guide_claude.html", {"limites": limites_affichees(request.user)})


# ---------- Connexion, mot de passe oublié, « Mon compte » ----------

class ConnexionView(LoginView):
    """Connexion : un ancien compte sans courriel est envoyé sur « Mon compte » pour l'ajouter."""
    template_name = "accounts/login.html"

    def get_success_url(self):
        adresse = self.get_redirect_url()   # ex. retour vers l'autorisation d'un agent IA : on ne l'interrompt pas
        if not adresse and not self.request.user.email:
            messages.info(self.request, "Ajoute ton adresse courriel : elle te permettra de retrouver ton compte "
                                        "si tu oublies ton mot de passe.")
            return reverse("mon_compte")
        return adresse or resolve_url(settings.LOGIN_REDIRECT_URL)


class MotDePasseOublieView(PasswordResetView):
    """Envoie le lien par courriel. Même message que le compte existe ou non (on ne révèle pas qui est inscrit)."""
    template_name = "accounts/mot_de_passe_oublie.html"
    email_template_name = "accounts/courriels/mot_de_passe_oublie.txt"
    subject_template_name = "accounts/courriels/mot_de_passe_oublie_sujet.txt"
    success_url = reverse_lazy("password_reset_done")

    def form_valid(self, form):
        if limite_atteinte(self.request, "reinitialisation", settings.LIMITE_REINITIALISATION_PAR_HEURE):
            return redirect(self.success_url)   # rien n'est envoyé, sans le dire (anti-abus)
        return super().form_valid(form)


@login_required
def mon_compte(request):
    if request.method == "POST":
        form = CourrielForm(request.user, request.POST)
        if form.is_valid():
            request.user.email = form.cleaned_data["email"]
            request.user.save(update_fields=["email"])
            messages.success(request, "Ton adresse courriel est enregistrée.")
            return redirect("mon_compte")
    else:
        form = CourrielForm(request.user, initial={"email": request.user.email})
    from .offres import resume
    return render(request, "accounts/mon_compte.html", {
        "form": form, "offre": resume(request.user),
        "url_paiement_pro": settings.URL_PAIEMENT_PRO, "url_gerer_abonnement": settings.URL_GERER_ABONNEMENT,
    })


# ---------- Contact / support ----------

def contact(request):
    """Le message part par courriel à l'adresse de support ; il n'est pas enregistré sur le site."""
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            if form.cleaned_data["site_web"]:   # robot : on fait comme si tout allait bien
                return redirect("contact_envoye")
            if limite_atteinte(request, "contact", settings.LIMITE_CONTACT_PAR_HEURE, maximum_global=50):
                messages.error(request, "Trop de messages envoyés en peu de temps. Réessaie dans une heure, "
                                        f"ou écris directement à {settings.SUPPORT_EMAIL}.")
                return render(request, "accounts/contact.html", {"form": form})
            sujet = dict(ContactForm.SUJETS)[form.cleaned_data["sujet"]]
            compte = request.user.username if request.user.is_authenticated else "visiteur sans compte"
            corps = (f"Sujet : {sujet}\nCourriel : {form.cleaned_data['email']}\nCompte : {compte}\n\n"
                     f"{form.cleaned_data['message']}")
            try:
                EmailMessage(f"[Contact] {sujet}", corps, None, [settings.SUPPORT_EMAIL],
                             reply_to=[form.cleaned_data["email"]]).send()
            except Exception:
                journal.exception("Message de contact non envoyé")
                messages.error(request, "Ton message n'a pas pu partir (problème d'envoi de courriel). "
                                        f"Réessaie plus tard, ou écris directement à {settings.SUPPORT_EMAIL}.")
                return render(request, "accounts/contact.html", {"form": form})
            return redirect("contact_envoye")
    else:
        initial = {"email": request.user.email} if request.user.is_authenticated else {}
        form = ContactForm(initial=initial)
    return render(request, "accounts/contact.html", {"form": form})


def contact_envoye(request):
    return render(request, "accounts/contact_envoye.html")


# ---------- Liste d'attente avant la limite Google de 100 utilisateurs ----------

def liste_attente_active():
    if settings.GOOGLE_APPLICATION_VERIFIEE:
        return False
    return ConnexionGoogle.objects.count() >= settings.SEUIL_LISTE_ATTENTE_GOOGLE


@login_required
def connecter_ma_chaine(request):
    """Remplace l'adresse « Connecter ma chaîne » : au-delà du seuil, liste d'attente (sauf pour une reconnexion)."""
    deja_compte = ConnexionGoogle.objects.filter(user=request.user).exists()
    if liste_attente_active() and not deja_compte:
        return redirect("liste_attente")
    return connecter_youtube(request)


@login_required
def liste_attente(request):
    inscription = ListeAttente.objects.filter(user=request.user).first()
    if request.method == "POST" and inscription is None:
        form = ListeAttenteForm(request.POST)
        if form.is_valid():
            inscription = ListeAttente.objects.create(user=request.user, email=form.cleaned_data["email"])
            try:
                send_mail("[Liste d'attente] Nouvelle inscription",
                          f"{request.user.username} attend une place pour connecter sa chaîne. "
                          f"Personnes en attente : {ListeAttente.objects.count()}. "
                          "Pense à demander la vérification de l'application Google.",
                          None, [settings.SUPPORT_EMAIL])
            except Exception:
                journal.exception("Avis liste d'attente non envoyé")
            messages.success(request, "C'est noté : nous t'écrirons dès qu'une place se libère.")
            return redirect("liste_attente")
    else:
        form = ListeAttenteForm(initial={"email": request.user.email})
    return render(request, "accounts/liste_attente.html", {"form": form, "inscription": inscription})
