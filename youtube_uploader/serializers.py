from rest_framework import serializers
from rest_framework.fields import empty
from .models import Video
from .validation import probleme_fichier


class ChampOuiNon(serializers.BooleanField):
    # Par défaut, DRF met False quand le champ manque dans un envoi avec -F.
    # Ici, un champ absent donne une erreur : l'utilisateur doit choisir lui-même.
    default_empty_html = empty


class VideoSerializer(serializers.ModelSerializer):
    pour_enfants = ChampOuiNon()

    class Meta:
        model = Video
        fields = ["id", "titre", "description", "fichier", "pour_enfants",'contenu_ia', "etat", "youtube_id", "erreur", "created_at"]
        read_only_fields = ["etat", "youtube_id", "erreur", "created_at"]
        # Le fichier est reçu, mais jamais renvoyé : pas de chemin du serveur dans les réponses
        extra_kwargs = {"fichier": {"write_only": True}}

    def validate_fichier(self, fichier):
        probleme = probleme_fichier(fichier)
        if probleme:
            raise serializers.ValidationError(probleme)
        return fichier
