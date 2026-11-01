from django.contrib import admin

from .models import CleApi


@admin.register(CleApi)
class CleApiAdmin(admin.ModelAdmin):
    list_display = ["nom", "user", "debut", "created_at", "dernier_usage"]
    fields = ["nom", "user", "debut", "created_at", "dernier_usage"]
    readonly_fields = fields   # une clé ne se crée que depuis « Mes clés » (affichée une seule fois)

    def has_add_permission(self, request):
        return False
