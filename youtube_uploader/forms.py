from django import forms
from .models import Video
from .validation import probleme_fichier


class VideoForm(forms.ModelForm):
    pour_enfants = forms.TypedChoiceField(
        label="Cette vidéo est-elle conçue pour les enfants ?",
        choices=[("True", "Oui"), ("False", "Non")],
        coerce=lambda x: x == "True",
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Video
        fields = ["titre", "description", "fichier", "pour_enfants",'contenu_ia']

    def clean_fichier(self):
        fichier = self.cleaned_data["fichier"]
        probleme = probleme_fichier(fichier)
        if probleme:
            raise forms.ValidationError(probleme)
        return fichier
