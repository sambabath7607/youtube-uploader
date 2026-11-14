from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


def courriel_deja_pris(courriel, sauf_user=None):
    """Un courriel ne sert qu'à un seul compte (sans tenir compte des majuscules)."""
    comptes = User.objects.filter(email__iexact=courriel)
    if sauf_user is not None:
        comptes = comptes.exclude(pk=sauf_user.pk)
    return comptes.exists()


class InscriptionForm(UserCreationForm):
    email = forms.EmailField(
        label="Adresse courriel",
        help_text="Elle sert à retrouver ton compte si tu oublies ton mot de passe, et à te prévenir quand ta vidéo est en ligne.",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    age_minimum = forms.BooleanField(
        label="J'ai au moins 13 ans (ou l'âge minimum exigé dans mon pays).",
    )
    accepte_conditions = forms.BooleanField(
        label="J'accepte les conditions d'utilisation et la politique de confidentialité.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_email(self):
        courriel = self.cleaned_data["email"].strip()
        if courriel_deja_pris(courriel):
            raise forms.ValidationError(
                "Un compte utilise déjà ce courriel. Connecte-toi, ou choisis « Mot de passe oublié » sur la page de connexion."
            )
        return courriel


class CourrielForm(forms.Form):
    """Ajouter ou changer son courriel (page « Mon compte ») ; le mot de passe protège contre un vol de session."""
    email = forms.EmailField(label="Adresse courriel", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    mot_de_passe = forms.CharField(
        label="Ton mot de passe actuel (pour confirmer)",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        courriel = self.cleaned_data["email"].strip()
        if courriel_deja_pris(courriel, sauf_user=self.user):
            raise forms.ValidationError("Ce courriel est déjà utilisé par un autre compte.")
        return courriel

    def clean_mot_de_passe(self):
        mot_de_passe = self.cleaned_data["mot_de_passe"]
        if not self.user.check_password(mot_de_passe):
            raise forms.ValidationError("Mot de passe incorrect.")
        return mot_de_passe


class ContactForm(forms.Form):
    SUJETS = [
        ("question", "Une question sur le service"),
        ("probleme", "Un problème technique"),
        ("donnees", "Mes données personnelles"),
        ("autre", "Autre chose"),
    ]
    sujet = forms.ChoiceField(label="Sujet", choices=SUJETS)
    email = forms.EmailField(
        label="Ton courriel (pour te répondre)", widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )
    message = forms.CharField(label="Ton message", min_length=10, max_length=5000,
                              widget=forms.Textarea(attrs={"rows": 6}))
    # Piège à robots : champ caché aux personnes ; s'il est rempli, le message est ignoré
    site_web = forms.CharField(required=False, label="Ne pas remplir ce champ",
                               widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))


class ListeAttenteForm(forms.Form):
    email = forms.EmailField(
        label="Ton courriel (pour te prévenir dès qu'une place se libère)",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
