"""Anti-abus simple (formulaire Contact, mot de passe oublié) : compteur par heure dans le cache.
L'adresse IP n'est jamais enregistrée telle quelle : seule son empreinte sert de clé, et elle disparaît après 1 heure."""
import hashlib

from django.core.cache import cache

UNE_HEURE = 60 * 60


def adresse_ip(request):
    # Derrière Nginx, la vraie adresse est la dernière ajoutée à X-Forwarded-For
    transmise = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if transmise:
        return transmise.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def limite_atteinte(request, action, maximum, maximum_global=None):
    """Compte une tentative ; renvoie True si la limite par heure est dépassée (pour cette adresse ou pour tout le site)."""
    empreinte_ip = hashlib.sha256(adresse_ip(request).encode()).hexdigest()[:32]
    cles = [(f"limite:{action}:{empreinte_ip}", maximum)]
    if maximum_global:
        cles.append((f"limite:{action}:tout", maximum_global))
    for cle, _ in cles:
        cache.add(cle, 0, UNE_HEURE)
    depasse = False
    for cle, plafond in cles:
        try:
            if cache.incr(cle) > plafond:
                depasse = True
        except ValueError:   # clé expirée entre-temps
            cache.set(cle, 1, UNE_HEURE)
    return depasse
