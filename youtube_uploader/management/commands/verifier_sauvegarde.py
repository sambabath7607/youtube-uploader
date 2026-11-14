from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from youtube_uploader.exploitation import verifier_sauvegarde


class Command(BaseCommand):
    help = ("Vérifie qu'une copie de la base se restaure : intégrité, tables et colonnes du site, migrations. "
            "Sans argument : la copie la plus récente de DOSSIER_SAUVEGARDES. N'affiche aucune donnée personnelle.")

    def add_arguments(self, parser):
        parser.add_argument("chemin", nargs="?", help="Fichier .sqlite3 à vérifier (facultatif).")

    def handle(self, *args, **options):
        chemin = options["chemin"]
        if not chemin:
            copies = sorted(Path(settings.DOSSIER_SAUVEGARDES).glob("db_*.sqlite3"))
            if not copies:
                raise CommandError(f"Aucune copie dans {settings.DOSSIER_SAUVEGARDES}.")
            chemin = copies[-1]
        try:
            r = verifier_sauvegarde(chemin)
        except ValueError as e:
            raise CommandError(f"Copie NON restaurable : {e}")
        self.stdout.write(f"Copie restaurable : {r['fichier']} ({r['taille_mo']} Mo, {r['comptes']} comptes, "
                          f"{r['videos']} vidéos).")
        if r["migrations_a_appliquer"]:
            self.stdout.write(f"Après restauration, lancer « python manage.py migrate » "
                              f"({len(r['migrations_a_appliquer'])} migration(s) plus récentes que la copie).")
        else:
            self.stdout.write("Migrations à jour : le site peut démarrer sur cette copie.")
