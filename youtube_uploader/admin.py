from django.contrib import admin

from .models import PreferencesPublication, Video, VoixUtilisateur, YouTubeCredentials


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ["titre", "user", "etat", "visibilite", "created_at"]
    list_filter = ["etat", "visibilite"]


@admin.register(YouTubeCredentials)
class YouTubeCredentialsAdmin(admin.ModelAdmin):
    list_display = ["user", "chaine_titre", "updated_at"]
    exclude = ["token_json"]   # le jeton Google chiffré n'est jamais affiché


@admin.register(VoixUtilisateur)
class VoixUtilisateurAdmin(admin.ModelAdmin):
    """« quota_secondes » : minutes de voix par mois de l'utilisateur (600 = 10 min offertes ; plus pour l'offre Pro)."""
    list_display = ["user", "mode", "voix_validee", "quota_secondes", "secondes_utilisees"]
    fields = ["user", "mode", "quota_secondes", "secondes_utilisees", "voix_validee", "consentement_le"]
    readonly_fields = ["user", "consentement_le"]


@admin.register(PreferencesPublication)
class PreferencesPublicationAdmin(admin.ModelAdmin):
    list_display = ["user", "pour_enfants", "contenu_ia", "visibilite"]
