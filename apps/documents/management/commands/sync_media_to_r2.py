"""
Management command to synchronize local media proof files to Cloudflare R2 bucket.

Usage:
  python manage.py sync_media_to_r2
  python manage.py sync_media_to_r2 --dry-run
"""
import os
from django.conf import settings
from django.core.management.base import BaseCommand
from apps.documents.models import ActivityDocument
from apps.documents.r2 import R2StorageService


class Command(BaseCommand):
    help = "Syncs local media files and document attachments to Cloudflare R2 object storage."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Scan files and report what would be uploaded without making any changes'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        self.stdout.write(self.style.MIGRATE_HEADING("=== Synchronizing Media Files to Cloudflare R2 ==="))

        service = R2StorageService.get_default()
        if not service.is_configured:
            self.stdout.write(self.style.ERROR("[!] Cloudflare R2 is not configured. Check your .env file."))
            return

        success, msg = service.test_connection()
        if not success:
            self.stdout.write(self.style.ERROR(f"[!] R2 connection failed: {msg}"))
            return

        self.stdout.write(self.style.SUCCESS(f"[✓] Connected to bucket '{service.config.bucket_name}'\n"))

        docs = ActivityDocument.objects.all().select_related('activity')
        self.stdout.write(f"Scanning {docs.count()} database document records...")

        synced_count = 0
        already_present = 0
        missing_count = 0

        for doc in docs:
            if not doc.file or not doc.file.name:
                continue

            storage_key = doc.file.name

            # Check if already present in R2
            in_r2 = False
            try:
                service.head_file(storage_key)
                in_r2 = True
            except Exception:
                pass

            if in_r2:
                already_present += 1
                continue

            # Check if file exists locally
            local_path = os.path.join(settings.MEDIA_ROOT, storage_key)
            if not os.path.exists(local_path):
                self.stdout.write(self.style.WARNING(f" [!] Missing locally and in R2: {storage_key} (Doc ID: {doc.id})"))
                missing_count += 1
                continue

            # Upload to Cloudflare R2
            file_size = os.path.getsize(local_path)
            self.stdout.write(f" Uploading: {storage_key} ({file_size} bytes)...")

            if not dry_run:
                try:
                    with open(local_path, 'rb') as f:
                        data = f.read()
                    service.upload_file(data, storage_key, content_type=doc.mime_type)
                    synced_count += 1
                    self.stdout.write(self.style.SUCCESS(f"  [✓] Uploaded: {storage_key}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  [✗] Failed to upload {storage_key}: {e}"))
            else:
                synced_count += 1

        self.stdout.write("\n" + self.style.MIGRATE_HEADING("=== Sync Summary ==="))
        self.stdout.write(f"Total Documents:    {docs.count()}")
        self.stdout.write(f"Already in R2:      {already_present}")
        self.stdout.write(f"{'Would Upload' if dry_run else 'Uploaded to R2'}:    {synced_count}")
        self.stdout.write(f"Missing Everywhere: {missing_count}")
