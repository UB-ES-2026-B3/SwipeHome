from django.core.management.base import BaseCommand, CommandError

from accounts import repository


class Command(BaseCommand):
    help = "Recupera lotes pendientes de avisos de cierre US9 sin duplicarlos."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 1000:
            raise CommandError("limit debe estar entre 1 y 1000.")
        try:
            processed = repository.process_selection_notifications(limit=options["limit"])
        except Exception as error:
            raise CommandError("No se pudieron procesar los avisos; se pueden reintentar.") from None
        self.stdout.write(f"Lotes procesados: {processed}")
