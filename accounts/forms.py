from django import forms
from django.contrib.auth.forms import UserCreationForm


class InscriptionForm(UserCreationForm):
    age_minimum = forms.BooleanField(
        label="J'ai au moins 13 ans (ou l'âge minimum exigé dans mon pays).",
    )
    accepte_conditions = forms.BooleanField(
        label="J'accepte les conditions d'utilisation et la politique de confidentialité.",
    )
