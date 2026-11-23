from django.core.management.base import BaseCommand

from accounts.repository import process_photo_cleanup


class Command(BaseCommand):
    help = "Reintenta la limpieza de fotografías pendientes."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        processed = process_photo_cleanup(limit=options["limit"])
        self.stdout.write(f"Limpiezas completadas: {processed}")
