import getpass
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from apps.tenants.models import Tenant
from apps.accounts.models import User, Role


class Command(BaseCommand):
    help = "Creates an institutional Tenant Admin bound to a specific tenant."

    def add_arguments(self, parser):
        parser.add_argument('--tenant', type=str, help="Tenant code, name, or UUID")
        parser.add_argument('--email', type=str, help="Tenant admin email address")
        parser.add_argument('--username', type=str, help="Optional username (defaults to email)")
        parser.add_argument('--password', type=str, help="Tenant admin password")
        parser.add_argument('--first-name', type=str, default="", help="First name")
        parser.add_argument('--last-name', type=str, default="", help="Last name")
        parser.add_argument('--phone', type=str, default="", help="Contact phone")
        parser.add_argument('--noinput', '--no-input', action='store_true', help="Do NOT prompt for input")

    def handle(self, *args, **options):
        tenant_arg = options.get('tenant')
        email = options.get('email')
        username = options.get('username')
        password = options.get('password')
        first_name = options.get('first_name', '')
        last_name = options.get('last_name', '')
        phone = options.get('phone', '')
        noinput = options.get('noinput', False)

        # 1. Resolve Tenant
        if not tenant_arg:
            if noinput:
                raise CommandError("--tenant is required in non-interactive mode.")
            tenants = list(Tenant.objects.filter(is_active=True).order_by('name'))
            if not tenants:
                raise CommandError("No active tenants found. Please create a tenant first.")
            self.stdout.write("Available Active Tenants:")
            for idx, t in enumerate(tenants, 1):
                self.stdout.write(f"  [{idx}] {t.name} (Code: {t.code})")
            choice = input(f"Select tenant [1-{len(tenants)}]: ").strip()
            try:
                tenant = tenants[int(choice) - 1]
            except Exception:
                raise CommandError("Invalid tenant selection.")
        else:
            tenant = Tenant.objects.filter(
                Q(code__iexact=tenant_arg) | Q(name__iexact=tenant_arg) | Q(id__iexact=tenant_arg)
            ).first()
            if not tenant:
                raise CommandError(f"Tenant '{tenant_arg}' not found.")

        # 2. Resolve Email
        if not email:
            if noinput:
                raise CommandError("--email is required in non-interactive mode.")
            email = input("Tenant Admin Email: ").strip()
        if not email:
            raise CommandError("Email cannot be empty.")
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError(f"User with email '{email}' already exists.")

        # 3. Resolve Username
        if username:
            if User.objects.filter(username__iexact=username).exists():
                raise CommandError(f"Error: That username '{username}' is already taken.")
        else:
            candidate = email.split('@')[0]
            if not User.objects.filter(username__iexact=candidate).exists():
                username = candidate
            elif not User.objects.filter(username__iexact=email).exists():
                username = email
            elif not noinput:
                while not username:
                    val = input("Username: ").strip()
                    if not val:
                        self.stdout.write(self.style.WARNING("Username cannot be empty."))
                        continue
                    if User.objects.filter(username__iexact=val).exists():
                        self.stdout.write(self.style.ERROR(f"Error: Username '{val}' is already taken. Try again."))
                        continue
                    username = val
            else:
                raise CommandError(f"Error: Derived username '{candidate}' is already taken. Please specify a unique --username.")

        # 4. Resolve Password
        if not password:
            if noinput:
                raise CommandError("--password is required in non-interactive mode.")
            p1 = getpass.getpass("Password: ")
            p2 = getpass.getpass("Password (again): ")
            if p1 != p2:
                raise CommandError("Passwords do not match.")
            password = p1
        if not password:
            raise CommandError("Password cannot be empty.")

        # 5. Resolve or create institutional super_admin Role
        admin_role, _ = Role.objects.get_or_create(
            tenant=tenant,
            code='super_admin',
            defaults={
                'name': f"{tenant.code} Super Admin",
                'description': f"Institutional Tenant Administrator for {tenant.name}"
            }
        )

        # 6. Create User
        user = User(
            tenant=tenant,
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            role=admin_role,
            is_staff=True,
            is_active=True,
            is_approved=True,
        )
        user.set_password(password)
        user.save()

        self.stdout.write(self.style.SUCCESS(
            f"Successfully created Tenant Admin '{user.email}' (username: {user.username}) "
            f"for tenant '{tenant.name}' [{tenant.code}]."
        ))
