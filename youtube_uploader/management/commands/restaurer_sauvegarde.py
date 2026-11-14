from django.core.management.base import BaseCommand, CommandError

from youtube_uploader.exploitation import copies_hors_serveur, restaurer_copie, verifier_sauvegarde


class Command(BaseCommand):
    help = ("Copies chiffrées hors du serveur (volume Modal privé) : --liste pour les voir, ou NOM --vers FICHIER pour "
            "en déchiffrer une (SAUVEGARDE_CLE dans .env). Ne remplace jamais la base en service.")

    def add_arguments(self, parser):
        parser.add_argument("nom", nargs="?", help="Nom de la copie (voir --liste).")
        parser.add_argument("--vers", help="Fichier à créer, par exemple restauration.sqlite3.")
        parser.add_argument("--liste", action="store_true", help="Lister les copies hors du serveur.")

    def handle(self, *args, **options):
        if options["liste"]:
            for nom in copies_hors_serveur():
                self.stdout.write(nom)
            return
        if not options["nom"] or not options["vers"]:
            raise CommandError("Indique la copie et le fichier à créer : restaurer_sauvegarde NOM --vers FICHIER")
        try:
            cible = restaurer_copie(options["nom"], options["vers"])
            r = verifier_sauvegarde(cible)
        except ValueError as e:
            raise CommandError(str(e))
        except Exception as e:
            raise CommandError(f"Restauration impossible ({type(e).__name__}) : vérifie SAUVEGARDE_CLE et le nom.")
        self.stdout.write(f"Copie déchiffrée dans {cible} et vérifiée : {r['comptes']} comptes, {r['videos']} vidéos.")
