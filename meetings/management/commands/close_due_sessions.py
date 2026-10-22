from django.core.management.base import BaseCommand

from meetings.models import MeetingSession


class Command(BaseCommand):
    help = "Persist clock-driven session transitions (open/close). Optional: attendance rules never depend on it."

    def handle(self, *args, **options):
        closed, opened = MeetingSession.sync_statuses()
        self.stdout.write(f"Opened {opened} session(s), closed {closed} session(s).")
