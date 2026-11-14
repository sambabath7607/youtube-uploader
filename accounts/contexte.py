from django.conf import settings


def support(request):
    """Adresse de support affichée dans les pages (conditions, confidentialité, contact)."""
    return {"adresse_support": settings.SUPPORT_EMAIL}
