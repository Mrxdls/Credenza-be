import os
import glob
from pathlib import Path
from django.core.management.base import BaseCommand
from apps.core.services.ingestion_service import BulkIngestionService
from apps.activities.models import ActivityStatus


class Command(BaseCommand):
    help = "Imports legacy Excel workbooks (Journals, Conferences, Patents, FDPs) from the project directory."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dir',
            type=str,
            default=str(Path(__file__).resolve().parent.parent.parent.parent.parent),
            help="Directory path containing the Excel files"
        )
        parser.add_argument(
            '--status',
            type=str,
            default='submitted',
            choices=['draft', 'submitted', 'under_review', 'approved'],
            help="Default status for imported activities"
        )

    def handle(self, *args, **options):
        search_dir = options['dir']
        import_status = getattr(ActivityStatus, options['status'].upper(), ActivityStatus.SUBMITTED)

        self.stdout.write(self.style.NOTICE(f"Scanning for Excel workbooks in: {search_dir}"))
        xlsx_files = sorted(glob.glob(os.path.join(search_dir, "*.xlsx")))

        if not xlsx_files:
            self.stdout.write(self.style.WARNING("No .xlsx files found."))
            return

        total_created = 0
        total_updated = 0
        total_skipped = 0

        for file_path in xlsx_files:
            filename = os.path.basename(file_path)
            self.stdout.write(self.style.MIGRATE_HEADING(f"\nProcessing: {filename}"))
            try:
                with open(file_path, 'rb') as f:
                    result = BulkIngestionService.process_xlsx(f, default_status=import_status, filename=filename)

                if result.get("success"):
                    created = result.get("created", 0)
                    updated = result.get("updated", 0)
                    skipped = result.get("skipped", 0)
                    total_created += created
                    total_updated += updated
                    total_skipped += skipped
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  -> Ingested: {created} created, {updated} updated, {skipped} skipped (Total: {result.get('total_processed', 0)})"
                        )
                    )
                else:
                    errors = result.get("errors", [])
                    self.stdout.write(self.style.ERROR(f"  -> Failed: {result.get('error', 'Validation errors')}"))
                    for err in errors[:5]:
                        self.stdout.write(f"     Row {err.get('row')}: {err.get('field')} - {err.get('error')}")
                    if len(errors) > 5:
                        self.stdout.write(f"     ... and {len(errors) - 5} more errors.")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  -> Exception processing {filename}: {e}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\n======================================================\n"
                f"[DONE] Legacy Excel Import Summary:\n"
                f"  Total Created: {total_created}\n"
                f"  Total Updated: {total_updated}\n"
                f"  Total Skipped: {total_skipped}\n"
                f"======================================================"
            )
        )
