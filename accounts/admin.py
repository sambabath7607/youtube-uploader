from django.contrib import admin

from django.conf import settings
from django.db.models import Q, Sum
from django.utils import timezone

from .models import Abonnement, CleApi, CoutClient, EvenementPont, ListeAttente
from .offres import _video_a_une_duree, debut_du_mois, offre_du_compte


@admin.register(CleApi)
class CleApiAdmin(admin.ModelAdmin):
    list_display = ["nom", "user", "debut", "created_at", "dernier_usage"]
    fields = ["nom", "user", "debut", "created_at", "dernier_usage"]
    readonly_fields = fields   # une clé ne se crée que depuis « Mes clés » (affichée une seule fois)

    def has_add_permission(self, request):
        return False


@admin.register(ListeAttente)
class ListeAttenteAdmin(admin.ModelAdmin):
    list_display = ["user", "email", "created_at"]
    readonly_fields = ["user", "email", "created_at"]

    def has_add_permission(self, request):
        return False


# ---------- Offres et pont (lot 4) ----------

@admin.register(Abonnement)
class AbonnementAdmin(admin.ModelAdmin):
    """Rempli par le pont du site vitrine. Une modification à la main est possible (geste commercial), mais le prochain
    appel du site vitrine (ou le rattrapage quotidien) la remplacera."""
    list_display = ["user", "email", "offre", "actif", "fin_periode", "statut_vitrine", "updated_at"]
    list_filter = ["offre", "actif"]
    search_fields = ["user__username", "email"]
    readonly_fields = ["reference", "dernier_evenement", "etat_le", "updated_at"]


@admin.register(EvenementPont)
class EvenementPontAdmin(admin.ModelAdmin):
    list_display = ["identifiant", "recu_le"]
    readonly_fields = ["identifiant", "recu_le"]

    def has_add_permission(self, request):
        return False


@admin.register(CoutClient)
class CoutClientAdmin(admin.ModelAdmin):
    """L4 : minutes de voix et de vidéo du mois par client, et coût Modal estimé
    (tarifs COUT_MODAL_MINUTE_VOIX et COUT_MODAL_MINUTE_VIDEO saisis par Samba dans .env)."""
    list_display = ["username", "email", "offre", "minutes_voix", "minutes_video", "cout_estime"]
    search_fields = ["username", "email"]
    fields = ["username", "email"]
    readonly_fields = fields
    ordering = ["username"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        debut = debut_du_mois()
        qs = super().get_queryset(request).select_related("voix")
        if _video_a_une_duree():
            qs = qs.annotate(secondes_video=Sum("video__duree_secondes", filter=Q(
                video__created_at__gte=debut) & ~Q(video__modele="") & ~Q(video__etat="fabrication_echouee")))
        return qs

    @admin.display(description="offre")
    def offre(self, obj):
        return settings.OFFRES[offre_du_compte(obj)[0]]["nom"]

    def _secondes_voix(self, obj):
        voix = getattr(obj, "voix", None)
        if voix is None or voix.mois_du_compteur != timezone.localdate().replace(day=1):
            return 0
        return voix.secondes_utilisees

    @admin.display(description="voix (min)")
    def minutes_voix(self, obj):
        return round(self._secondes_voix(obj) / 60, 1)

    @admin.display(description="vidéo (min)")
    def minutes_video(self, obj):
        return round((getattr(obj, "secondes_video", 0) or 0) / 60, 1)

    @admin.display(description="coût Modal estimé ($)")
    def cout_estime(self, obj):
        cout = (self._secondes_voix(obj) / 60 * settings.COUT_MODAL_MINUTE_VOIX
                + (getattr(obj, "secondes_video", 0) or 0) / 60 * settings.COUT_MODAL_MINUTE_VIDEO)
        return f"{cout:.2f}"
