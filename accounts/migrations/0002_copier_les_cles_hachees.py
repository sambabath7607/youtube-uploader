import hashlib

from django.db import migrations


def copier_les_cles(apps, schema_editor):
    """Chaque clé actuelle continue de marcher : on garde son empreinte, puis la clé en clair est effacée."""
    Token = apps.get_model("authtoken", "Token")
    CleApi = apps.get_model("accounts", "CleApi")
    for token in Token.objects.all():
        CleApi.objects.update_or_create(
            user_id=token.user_id,
            defaults={"empreinte": hashlib.sha256(token.key.encode()).hexdigest(), "debut": token.key[:8]},
        )
    Token.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("authtoken", "0004_alter_tokenproxy_options"),
    ]

    # Pas de retour en arrière possible : les clés en clair n'existent plus
    operations = [migrations.RunPython(copier_les_cles, migrations.RunPython.noop)]
