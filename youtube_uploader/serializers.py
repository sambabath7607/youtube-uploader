from rest_framework import serializers
from rest_framework.fields import empty
from .fabrication import MODELES, MUSIQUES, TYPES_SCENE, paragraphes
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
        fields = ["id", "titre", "description", "fichier", "pour_enfants", "contenu_ia", "visibilite", "etat",
                  "youtube_id", "erreur", "created_at", "modele", "etape", "duree_secondes"]
        read_only_fields = ["etat", "youtube_id", "erreur", "created_at", "modele", "etape", "duree_secondes"]
        # Le fichier est reçu, mais jamais renvoyé : pas de chemin du serveur dans les réponses
        extra_kwargs = {"fichier": {"write_only": True}}

    def validate_fichier(self, fichier):
        probleme = probleme_fichier(fichier)
        if probleme:
            raise serializers.ValidationError(probleme)
        return fichier


class PreparationEnvoiSerializer(serializers.ModelSerializer):
    """Mêmes règles que VideoSerializer, sans le fichier : il sera déposé à l'adresse à usage unique."""
    pour_enfants = ChampOuiNon()

    class Meta:
        model = Video
        fields = ["id", "titre", "description", "pour_enfants", "contenu_ia", "visibilite"]


# ---------- Fabrication d'une vidéo à partir d'un modèle (POST /youtube/api/v1/fabrications/) ----------

MAX_POINTS, MAX_LIGNES_CODE = 6, 20


class SceneSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=list(TYPES_SCENE))
    texte = serializers.CharField(max_length=200)
    points = serializers.ListField(child=serializers.CharField(max_length=90), max_length=MAX_POINTS, required=False,
                                   default=list)
    code = serializers.CharField(max_length=1500, required=False, allow_blank=True, default="", trim_whitespace=False)
    langage = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")

    def validate(self, scene):
        if scene["type"] == "points" and not scene["points"]:
            raise serializers.ValidationError("Une scène « points » demande au moins un point (champ points).")
        if scene["type"] == "code":
            if not scene["code"].strip():
                raise serializers.ValidationError("Une scène « code » demande du code (champ code).")
            if len(scene["code"].splitlines()) > MAX_LIGNES_CODE:
                raise serializers.ValidationError(f"Code trop long : {MAX_LIGNES_CODE} lignes au maximum par scène.")
        return scene


class FabricationSerializer(serializers.Serializer):
    """Champs d'un modèle remplis par l'agent IA. Les messages d'erreur disent quoi corriger."""
    modele = serializers.ChoiceField(choices=list(MODELES))
    titre = serializers.CharField(max_length=100)
    description = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")
    script = serializers.CharField(max_length=120_000)
    scenes = SceneSerializer(many=True, allow_empty=False, max_length=30)
    pour_enfants = serializers.BooleanField()
    contenu_ia = serializers.BooleanField()
    avec_ma_voix = serializers.BooleanField(default=True)
    visibilite = serializers.ChoiceField(choices=Video.VISIBILITES, default="private")
    accent = serializers.RegexField(r"^#[0-9A-Fa-f]{6}$", required=False, default="#3B8BFF",
                                    error_messages={"invalid": "Couleur au format #RRGGBB, par exemple #3B8BFF."})
    musique = serializers.ChoiceField(choices=list(MUSIQUES), default="calme")

    def validate(self, donnees):
        modele = MODELES[donnees["modele"]]
        scenes = donnees["scenes"]
        refusees = sorted({s["type"] for s in scenes} - set(modele["types"]))
        if refusees:
            raise serializers.ValidationError({"scenes": f"Type de scène non disponible dans le modèle "
                                                         f"« {donnees['modele']} » : {', '.join(refusees)}."})
        maximum = modele.get("max_scenes", 30)
        if len(scenes) > maximum:
            raise serializers.ValidationError({"scenes": f"{maximum} scènes au maximum pour ce modèle."})
        nb = len(paragraphes(donnees["script"]))
        if nb != len(scenes):
            raise serializers.ValidationError({"script": f"Le script a {nb} paragraphe(s) et il y a {len(scenes)} "
                                                         "scène(s) : une scène = un paragraphe du script "
                                                         "(paragraphes séparés par une ligne vide)."})
        if donnees["avec_ma_voix"]:
            donnees["contenu_ia"] = True   # une voix clonée est un contenu modifié par IA (règle YouTube)
        return donnees
