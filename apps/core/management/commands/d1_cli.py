"""
Management command to manage and inspect Cloudflare D1 and Cloudflare R2 via REST API.

Pure API-driven management without Wrangler CLI dependency.
Credentials loaded from .env: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_D1_DATABASE_ID, CLOUDFLARE_D1_API_TOKEN.

Usage:
  python manage.py d1_cli --status
  python manage.py d1_cli --tables
  python manage.py d1_cli --read "SELECT count(*) FROM accounts_user;"
  python manage.py d1_cli --write "UPDATE accounts_user SET is_active=1 WHERE id=1;"
  python manage.py d1_cli --query "SELECT * FROM accounts_user LIMIT 5;"
  python manage.py d1_cli --export-schema schema_d1.sql
  python manage.py d1_cli --apply-schema
  python manage.py d1_cli --apply-schema=schema_d1.sql
  python manage.py d1_cli --execute-file=seed.sql
  python manage.py d1_cli --test-all
"""
import json
import os
from django.core.management.base import BaseCommand
from apps.core.services.d1_service import (
    CloudflareD1Service,
    execute_d1_query,
    execute_d1_read,
    execute_d1_write,
    execute_d1_script,
    apply_d1_schema,
    list_d1_tables,
    get_d1_config,
    get_d1_database_info,
    test_d1_connection,
    export_django_schema_for_d1,
)
from apps.documents.r2 import (
    get_r2_config,
    test_r2_connection,
    list_r2_files,
)


class Command(BaseCommand):
    help = "Cloudflare D1 Database & R2 Storage Management CLI (Direct REST API, No Wrangler Needed)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--status',
            action='store_true',
            help='Check connection and display Cloudflare D1 database status'
        )
        parser.add_argument(
            '--tables',
            action='store_true',
            help='List all remote tables and row counts in Cloudflare D1 database'
        )
        parser.add_argument(
            '--query',
            type=str,
            help='Execute any SQL statement on Cloudflare D1 remote database via API'
        )
        parser.add_argument(
            '--read',
            type=str,
            help='Execute a SQL read query (SELECT) and display returned rows and count'
        )
        parser.add_argument(
            '--write',
            type=str,
            help='Execute a SQL mutation statement (INSERT, UPDATE, DELETE, DDL) and display changes'
        )
        parser.add_argument(
            '--export-schema',
            type=str,
            nargs='?',
            const='cloudflare_d1_schema.sql',
            help='Export SQLite/D1-compatible database schema to SQL file (default: cloudflare_d1_schema.sql)'
        )
        parser.add_argument(
            '--apply-schema',
            type=str,
            nargs='?',
            const='__AUTO__',
            help='Apply schema directly to Cloudflare D1 via API (provide file path or omit to apply directly from Django models)'
        )
        parser.add_argument(
            '--execute-file',
            type=str,
            help='Execute a SQL script file directly on Cloudflare D1 via Cloudflare REST API'
        )
        parser.add_argument(
            '--test-r2',
            action='store_true',
            help='Test Cloudflare R2 bucket connection and credentials'
        )
        parser.add_argument(
            '--list-r2',
            action='store_true',
            help='List objects in the Cloudflare R2 bucket'
        )
        parser.add_argument(
            '--test-all',
            action='store_true',
            help='Test both Cloudflare D1 SQL and Cloudflare R2 connections'
        )

    def handle(self, *args, **options):
        if options['test_all']:
            self.test_all_services()
        elif options['status']:
            self.check_d1_status()
        elif options['tables']:
            self.list_d1_tables()
        elif options['read']:
            self.run_d1_read(options['read'])
        elif options['write']:
            self.run_d1_write(options['write'])
        elif options['query']:
            self.run_d1_query(options['query'])
        elif options['apply_schema']:
            self.apply_schema(options['apply_schema'])
        elif options['execute_file']:
            self.execute_file(options['execute_file'])
        elif options['export_schema']:
            self.export_schema(options['export_schema'])
        elif options['test_r2']:
            self.test_r2()
        elif options['list_r2']:
            self.list_r2()
        else:
            self.stdout.write(self.style.WARNING("No action specified. Use --help to view available options."))

    def check_d1_status(self):
        cfg = get_d1_config()
        self.stdout.write(self.style.MIGRATE_HEADING("=== Cloudflare D1 Status (REST API) ==="))
        self.stdout.write(f"Account ID:   {cfg['account_id'] or '[Not Set]'}")
        self.stdout.write(f"Database ID:  {cfg['database_id'] or '[Not Set]'}")
        self.stdout.write(f"API Token:    {'***' + cfg['api_token'][-4:] if cfg['api_token'] else '[Not Set]'}")

        if not cfg['account_id'] or not cfg['database_id'] or not cfg['api_token']:
            self.stdout.write(self.style.ERROR("\n[!] D1 credentials not fully configured in environment."))
            return

        success, msg = test_d1_connection(cfg)
        if success:
            self.stdout.write(self.style.SUCCESS(f"\n[✓] Connection successful: {msg}"))
            info = get_d1_database_info(cfg)
            if info.get('success'):
                db = info.get('database', {})
                self.stdout.write(f"Database Name:    {db.get('name', 'Unknown')}")
                self.stdout.write(f"Version:          {db.get('version', 'Unknown')}")
                self.stdout.write(f"Tables Count:     {db.get('num_tables', 0)}")
                self.stdout.write(f"File Size:        {db.get('file_size', 0)} bytes")
        else:
            self.stdout.write(self.style.ERROR(f"\n[✗] Connection test failed: {msg}"))

    def list_d1_tables(self):
        self.stdout.write(self.style.MIGRATE_HEADING("=== Remote Cloudflare D1 Tables ==="))
        try:
            service = CloudflareD1Service()
            table_counts = service.get_table_counts()
            if not table_counts:
                self.stdout.write("No tables found in remote Cloudflare D1 database.")
                return

            self.stdout.write(self.style.SUCCESS(f"Found {len(table_counts)} table(s):"))
            self.stdout.write(f"{'Table Name':<45} | {'Row Count':>10}")
            self.stdout.write("-" * 60)
            for table_name, count in sorted(table_counts.items()):
                self.stdout.write(f"{table_name:<45} | {count:>10}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[✗] Failed to list tables: {e}"))

    def run_d1_read(self, sql: str):
        self.stdout.write(self.style.MIGRATE_HEADING(f"Executing D1 Read: {sql}"))
        try:
            res = execute_d1_read(sql)
            if res.get('success'):
                rows = res.get('rows', [])
                self.stdout.write(self.style.SUCCESS(f"\n[✓] Query returned {len(rows)} row(s):"))
                if rows:
                    self.stdout.write(json.dumps(rows, indent=2, default=str))
                meta = res.get('meta', {})
                self.stdout.write(f"\nDuration: {meta.get('duration', 'N/A')}ms | Rows read: {meta.get('rows_read', 0)}")
            else:
                self.stdout.write(self.style.ERROR(f"\n[✗] Read query failed: {res.get('error')}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n[✗] Exception: {e}"))

    def run_d1_write(self, sql: str):
        self.stdout.write(self.style.MIGRATE_HEADING(f"Executing D1 Write: {sql}"))
        try:
            res = execute_d1_write(sql)
            if res.get('success'):
                meta = res.get('meta', {})
                self.stdout.write(self.style.SUCCESS("\n[✓] Write statement executed successfully:"))
                self.stdout.write(
                    f"Changes: {res.get('changes', 0)} | Rows written: {res.get('rows_written', 0)} | "
                    f"Last Row ID: {res.get('last_row_id', 'N/A')} | Duration: {meta.get('duration', 'N/A')}ms"
                )
            else:
                self.stdout.write(self.style.ERROR(f"\n[✗] Write failed: {res.get('error')}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n[✗] Exception: {e}"))

    def run_d1_query(self, sql: str):
        self.stdout.write(self.style.MIGRATE_HEADING(f"Executing D1 Query: {sql}"))
        try:
            res = execute_d1_query(sql)
            if res.get('success'):
                self.stdout.write(self.style.SUCCESS("\n[✓] Query executed successfully:"))
                results = res.get('results', [])
                if results:
                    self.stdout.write(json.dumps(results, indent=2, default=str))
                else:
                    self.stdout.write("Query returned 0 rows (or was a DDL/mutation statement).")
                meta = res.get('meta', {})
                self.stdout.write(f"\nDuration: {meta.get('duration', 'N/A')}ms | Rows read: {meta.get('rows_read', 0)} | Rows written: {meta.get('rows_written', 0)} | Changes: {meta.get('changes', 0)}")
            else:
                self.stdout.write(self.style.ERROR(f"\n[✗] Query failed: {res.get('error')}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n[✗] Exception: {e}"))

    def export_schema(self, output_path: str):
        self.stdout.write(f"Exporting D1 SQLite schema to '{output_path}'...")
        try:
            schema_sql = export_django_schema_for_d1()
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(schema_sql)
            self.stdout.write(self.style.SUCCESS(f"[✓] Schema exported successfully to {output_path} ({len(schema_sql)} bytes)"))
            self.stdout.write("To apply directly to Cloudflare D1 via REST API:")
            self.stdout.write(f"  python manage.py d1_cli --apply-schema={output_path}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[✗] Failed to export schema: {e}"))

    def apply_schema(self, schema_arg: str):
        if schema_arg == '__AUTO__':
            self.stdout.write("Applying current Django schema directly to Cloudflare D1 via API...")
            res = apply_d1_schema()
        else:
            self.stdout.write(f"Applying schema from '{schema_arg}' to Cloudflare D1 via API...")
            res = apply_d1_schema(schema_file=schema_arg)

        if res.get('success'):
            self.stdout.write(self.style.SUCCESS(
                f"[✓] Schema successfully applied to Cloudflare D1!\n"
                f"    Statements executed: {res.get('executed_statements', 0)} / {res.get('total_statements', 0)}\n"
                f"    Batches executed:    {res.get('batches_executed', 0)}\n"
                f"    Total duration:      {res.get('duration', 0)}s"
            ))
        else:
            self.stdout.write(self.style.ERROR(f"[✗] Failed to apply schema: {res.get('error')}"))

    def execute_file(self, file_path: str):
        self.stdout.write(f"Executing SQL file '{file_path}' on Cloudflare D1 via API...")
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f"[✗] File not found: {file_path}"))
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            res = execute_d1_script(content)
            if res.get('success'):
                self.stdout.write(self.style.SUCCESS(
                    f"[✓] SQL script executed successfully!\n"
                    f"    Statements executed: {res.get('executed_statements', 0)} / {res.get('total_statements', 0)}\n"
                    f"    Batches executed:    {res.get('batches_executed', 0)}\n"
                    f"    Changes:             {res.get('changes', 0)}\n"
                    f"    Total duration:      {res.get('duration', 0)}s"
                ))
            else:
                self.stdout.write(self.style.ERROR(f"[✗] Failed to execute SQL script: {res.get('error')}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[✗] Exception executing file: {e}"))

    def test_r2(self):
        cfg = get_r2_config()
        self.stdout.write(self.style.MIGRATE_HEADING("=== Cloudflare R2 Status ==="))
        self.stdout.write(f"Account ID:   {cfg['account_id'] or '[Not Set]'}")
        self.stdout.write(f"Bucket:       {cfg['bucket_name'] or '[Not Set]'}")
        self.stdout.write(f"Access Key:   {'***' + cfg['access_key_id'][-4:] if cfg['access_key_id'] else '[Not Set]'}")
        self.stdout.write(f"Endpoint:     {cfg['endpoint_url'] or '[Not Set]'}")

        if not cfg['account_id'] or not cfg['access_key_id'] or not cfg['secret_access_key']:
            self.stdout.write(self.style.ERROR("\n[!] Cloudflare R2 credentials not fully configured."))
            return

        success, msg = test_r2_connection(cfg)
        if success:
            self.stdout.write(self.style.SUCCESS(f"\n[✓] {msg}"))
        else:
            self.stdout.write(self.style.ERROR(f"\n[✗] {msg}"))

    def list_r2(self):
        self.stdout.write("Listing objects in Cloudflare R2 bucket...")
        try:
            items = list_r2_files(max_keys=20)
            self.stdout.write(self.style.SUCCESS(f"Found {len(items)} objects:"))
            for it in items:
                self.stdout.write(f" - {it['key']} ({it['size']} bytes, modified {it['last_modified']})")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to list R2 objects: {e}"))

    def test_all_services(self):
        self.stdout.write(self.style.MIGRATE_HEADING("========================================="))
        self.stdout.write(self.style.MIGRATE_HEADING(" Cloudflare Infrastructure Health Check  "))
        self.stdout.write(self.style.MIGRATE_HEADING("========================================="))
        self.check_d1_status()
        self.stdout.write("\n")
        self.test_r2()
