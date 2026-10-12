from django.test import TestCase
from apps.accounts.models import Department, Designation, Module, Role, RolePermission, User
from apps.accounts.permissions import HasModulePermission


class DynamicRBACTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Computer Science", code="CSE")
        self.desig = Designation.objects.create(name="Professor", code="PROF", priority=10)

        # Create Roles
        self.role_super_admin = Role.objects.create(name="Super Admin", code="super_admin")
        self.role_faculty = Role.objects.create(name="Faculty Member", code="faculty")
        self.role_coord = Role.objects.create(name="Coordinator", code="coordinator")

        # Create Modules
        self.mod_activities = Module.objects.create(name="Faculty Achievements", code="activities")
        self.mod_accounts = Module.objects.create(name="User Accounts", code="accounts")
        self.mod_documents = Module.objects.create(name="Documents", code="documents")
        self.mod_reports = Module.objects.create(name="Reports", code="reports")

        # Configure Permissions
        # Faculty: activities create/view/edit/export, NO approve, NO accounts
        RolePermission.objects.create(
            role=self.role_faculty,
            module=self.mod_activities,
            can_view=True,
            can_create=True,
            can_edit=True,
            can_approve=False,
            can_export=True
        )
        RolePermission.objects.create(
            role=self.role_faculty,
            module=self.mod_reports,
            can_view=True,
            can_export=True
        )
        RolePermission.objects.create(
            role=self.role_faculty,
            module=self.mod_accounts,
            can_view=False,
            can_create=False,
            can_edit=False
        )

        # Coordinator: activities approve=True, export=True; reports approve=True, export=True
        RolePermission.objects.create(
            role=self.role_coord,
            module=self.mod_activities,
            can_view=True,
            can_create=True,
            can_edit=True,
            can_approve=True,
            can_export=True
        )
        RolePermission.objects.create(
            role=self.role_coord,
            module=self.mod_reports,
            can_view=True,
            can_approve=True,
            can_export=True
        )

        # Users
        self.superuser = User.objects.create_superuser(
            username="root_admin",
            email="root@poornima.org",
            password="password123"
        )
        self.faculty_user = User.objects.create_user(
            username="faculty_test",
            email="faculty@poornima.org",
            password="password123",
            role=self.role_faculty,
            department=self.dept,
            is_staff=True  # Staff flag present
        )
        self.coord_user = User.objects.create_user(
            username="coord_test",
            email="coord@poornima.org",
            password="password123",
            role=self.role_coord,
            department=self.dept,
            is_staff=True
        )

    def test_superuser_has_all_module_permissions(self):
        self.assertTrue(self.superuser.has_module_perm("activities", "approve"))
        self.assertTrue(self.superuser.has_module_perm("accounts", "edit"))
        self.assertTrue(self.superuser.has_module_perm("reports", "export"))

    def test_faculty_staff_flag_does_not_grant_approval_or_accounts_edit(self):
        # Even with is_staff=True, module RBAC is strictly enforced
        self.assertTrue(self.faculty_user.is_staff)
        self.assertTrue(self.faculty_user.has_module_perm("activities", "view"))
        self.assertTrue(self.faculty_user.has_module_perm("activities", "create"))
        self.assertTrue(self.faculty_user.has_module_perm("activities", "export"))
        self.assertFalse(self.faculty_user.has_module_perm("activities", "approve"))
        self.assertFalse(self.faculty_user.has_module_perm("accounts", "edit"))
        self.assertFalse(self.faculty_user.has_module_perm("accounts", "view"))

    def test_coordinator_has_approval_and_export_permissions(self):
        self.assertTrue(self.coord_user.has_module_perm("activities", "approve"))
        self.assertTrue(self.coord_user.has_module_perm("activities", "export"))
        self.assertTrue(self.coord_user.has_module_perm("reports", "export"))
        self.assertFalse(self.coord_user.has_module_perm("accounts", "edit"))

    def test_has_module_perm_invalid_flag(self):
        self.assertFalse(self.faculty_user.has_module_perm("activities", "invalid_action"))

    def test_inactive_user_has_no_permissions(self):
        self.faculty_user.is_active = False
        self.faculty_user.save()
        self.assertFalse(self.faculty_user.has_module_perm("activities", "view"))


import io
from datetime import timedelta
from django.core.management import call_command
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from apps.tenants.models import Tenant
from apps.tenants.admin import TenantAdmin
from apps.activities.models import AcademicSession, Activity, ActivityStatus, ActivityType
from apps.documents.models import ActivityDocument
from django.contrib.admin.sites import site as default_admin_site


class MultiTenantOnboardingAndApprovalTests(APITestCase):
    def setUp(self):
        self.tenant_a = Tenant.objects.create(
            name="Alpha University",
            code="ALPHA",
            slug="alpha",
            is_active=True
        )
        self.tenant_b = Tenant.objects.create(
            name="Beta University",
            code="BETA",
            slug="beta",
            is_active=True
        )
        self.role_super_admin = Role.objects.create(name="Super Admin", code="super_admin", tenant=self.tenant_a)
        self.role_faculty = Role.objects.create(name="Faculty Member", code="faculty", tenant=self.tenant_a)
        self.role_coord = Role.objects.create(name="Coordinator", code="coordinator", tenant=self.tenant_a)

        self.mod_activities = Module.objects.create(name="Faculty Achievements", code="activities")
        RolePermission.objects.create(
            role=self.role_super_admin,
            module=self.mod_activities,
            can_view=True, can_create=True, can_edit=True, can_delete=True, can_approve=True, can_export=True
        )

        self.supreme_admin = User.objects.create_superuser(
            username="platform_owner",
            email="owner@platform.org",
            password="Password123!",
            tenant=None
        )
        self.tenant_a_admin = User.objects.create_user(
            username="tenant_a_admin",
            email="admin@alpha.edu",
            password="Password123!",
            tenant=self.tenant_a,
            role=self.role_super_admin,
            is_staff=True,
            is_active=True,
            is_approved=True
        )
        self.tenant_b_admin = User.objects.create_user(
            username="tenant_b_admin",
            email="admin@beta.edu",
            password="Password123!",
            tenant=self.tenant_b,
            role=self.role_super_admin,
            is_staff=True,
            is_active=True,
            is_approved=True
        )
        self.session_a = AcademicSession.objects.create(
            tenant=self.tenant_a,
            name="2025-2026",
            start_date="2025-07-01",
            end_date="2026-06-30",
            is_current=True
        )

    def test_createtenantadmin_management_command(self):
        """CLI createtenantadmin creates a fully provisioned institutional admin."""
        call_command(
            'createtenantadmin',
            '--tenant', self.tenant_a.code,
            '--email', 'new_admin@alpha.edu',
            '--username', 'new_alpha_admin',
            '--password', 'AdminSecret123!',
            '--first-name', 'Alpha',
            '--last-name', 'Admin',
            '--noinput'
        )
        admin_user = User.objects.filter(email='new_admin@alpha.edu').first()
        self.assertIsNotNone(admin_user)
        self.assertEqual(admin_user.tenant, self.tenant_a)
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_active)
        self.assertTrue(admin_user.is_approved)
        self.assertFalse(admin_user.is_superuser)
        self.assertEqual(admin_user.role.code, 'super_admin')
        self.assertTrue(admin_user.check_password('AdminSecret123!'))

    def test_tenant_admin_panel_permissions(self):
        """Super admin manages tenants in standard Django admin (/admin/); non-superusers are blocked."""
        from django.test import RequestFactory
        from django.contrib import admin
        factory = RequestFactory()

        tenant_admin_model = TenantAdmin(Tenant, admin.site)
        req_super = factory.get('/admin/tenants/tenant/')
        req_super.user = self.supreme_admin
        self.assertTrue(tenant_admin_model.has_module_permission(req_super))
        self.assertTrue(tenant_admin_model.has_view_permission(req_super))
        self.assertTrue(tenant_admin_model.has_change_permission(req_super))
        self.assertTrue(tenant_admin_model.has_add_permission(req_super))

        req_tenant = factory.get('/admin/tenants/tenant/')
        req_tenant.user = self.tenant_a_admin
        self.assertFalse(tenant_admin_model.has_module_permission(req_tenant))
        self.assertFalse(tenant_admin_model.has_view_permission(req_tenant))

    def test_user_registration_approval_gate(self):
        """Unapproved users cannot access protected views until approved by tenant admin."""
        unapproved = User.objects.create_user(
            username="pending_faculty",
            email="pending@alpha.edu",
            password="Password123!",
            tenant=self.tenant_a,
            role=self.role_faculty,
            is_active=False,
            is_approved=False
        )
        # Permissions are blocked
        self.assertFalse(unapproved.has_module_perm("activities", "view"))

        # Tenant Admin approves user via API
        self.client.force_authenticate(user=self.tenant_a_admin)
        res = self.client.post(f'/api/accounts/users/{unapproved.id}/approve/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        unapproved.refresh_from_db()
        self.assertTrue(unapproved.is_approved)
        self.assertTrue(unapproved.is_active)

    def test_bulk_approve_users(self):
        """Tenant admin can bulk-approve multiple pending users."""
        u1 = User.objects.create_user(username="u1", email="u1@alpha.edu", tenant=self.tenant_a, is_approved=False, is_active=False)
        u2 = User.objects.create_user(username="u2", email="u2@alpha.edu", tenant=self.tenant_a, is_approved=False, is_active=False)

        self.client.force_authenticate(user=self.tenant_a_admin)
        res = self.client.post('/api/accounts/users/bulk-approve/', {'user_ids': [str(u1.id), str(u2.id)]}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['updated_count'], 2)

        u1.refresh_from_db()
        u2.refresh_from_db()
        self.assertTrue(u1.is_approved and u1.is_active)
        self.assertTrue(u2.is_approved and u2.is_active)

    def test_sample_template_download(self):
        """Sample CSV and XLSX templates are downloadable."""
        self.client.force_authenticate(user=self.tenant_a_admin)
        res_csv = self.client.get('/api/accounts/users/sample-template/?format=csv')
        self.assertEqual(res_csv.status_code, status.HTTP_200_OK)
        self.assertIn("Name,Mobile Number,Email", res_csv.content.decode('utf-8'))

        res_xlsx = self.client.get('/api/accounts/users/sample-template/?format=xlsx')
        self.assertEqual(res_xlsx.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res_xlsx.content) > 100)

    def test_bulk_import_csv_and_password_setup(self):
        """Bulk import creates users with 7-day one-time link, which can be used to set password."""
        csv_data = "Name,Mobile Number,Email\nDr. Onboard One,9991112222,onboard1@alpha.edu\nDr. Onboard Two,9993334444,onboard2@alpha.edu\n"
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = "import_users.csv"

        self.client.force_authenticate(user=self.tenant_a_admin)
        res = self.client.post('/api/accounts/users/bulk-import/', {'file': csv_file}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['created'], 2)

        user1 = User.objects.get(email='onboard1@alpha.edu')
        self.assertEqual(user1.tenant, self.tenant_a)
        self.assertEqual(user1.phone, '9991112222')
        self.assertIsNotNone(user1.password_setup_token)
        self.assertTrue(user1.password_setup_expires_at > timezone.now() + timedelta(days=6))

        # Test setting password using token via public endpoint
        token = user1.password_setup_token
        self.client.logout()

        setup_res = self.client.post('/api/accounts/setup-password/', {
            'uid': str(user1.id),
            'token': token,
            'password': 'BrandNewPassword123!'
        }, format='json')
        self.assertEqual(setup_res.status_code, status.HTTP_200_OK)

        user1.refresh_from_db()
        self.assertTrue(user1.check_password('BrandNewPassword123!'))
        self.assertIsNone(user1.password_setup_token)

        # Attempting to reuse the one-time token fails
        reuse_res = self.client.post('/api/accounts/setup-password/', {
            'uid': str(user1.id),
            'token': token,
            'password': 'AnotherPassword123!'
        }, format='json')
        self.assertEqual(reuse_res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_assign_role(self):
        """Tenant admin can assign role to multiple users within tenant; cross-tenant assignment rejected."""
        u1 = User.objects.create_user(username="user1", email="u1_role@alpha.edu", tenant=self.tenant_a)
        u2 = User.objects.create_user(username="user2", email="u2_role@alpha.edu", tenant=self.tenant_a)
        u_b = User.objects.create_user(username="user_b", email="ub_role@beta.edu", tenant=self.tenant_b)

        self.client.force_authenticate(user=self.tenant_a_admin)
        res = self.client.post('/api/accounts/users/bulk-assign-role/', {
            'user_ids': [str(u1.id), str(u2.id), str(u_b.id)],
            'role_id': str(self.role_coord.id)
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['updated_count'], 2)  # Only the 2 Alpha users were updated

        u1.refresh_from_db()
        u2.refresh_from_db()
        u_b.refresh_from_db()
        self.assertEqual(u1.role, self.role_coord)
        self.assertEqual(u2.role, self.role_coord)
        self.assertNotEqual(u_b.role, self.role_coord)  # Beta user was untouched!

    def test_mass_verify_activities_and_documents(self):
        """Mass verify approves activities and verifies attached proof documents simultaneously."""
        faculty = User.objects.create_user(username="fac_act", email="fac_act@alpha.edu", tenant=self.tenant_a)
        act1 = Activity.objects.create(
            tenant=self.tenant_a,
            faculty=faculty,
            academic_session=self.session_a,
            title="Mass Verify Paper 1",
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            status=ActivityStatus.SUBMITTED
        )
        doc1 = ActivityDocument.objects.create(activity=act1, title="Doc 1", is_verified=False)
        doc2 = ActivityDocument.objects.create(activity=act1, title="Doc 2", is_verified=False)

        self.client.force_authenticate(user=self.tenant_a_admin)
        res = self.client.post('/api/activities/bulk-verify/', {
            'activity_ids': [str(act1.id)],
            'verify_documents': True
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        act1.refresh_from_db()
        doc1.refresh_from_db()
        doc2.refresh_from_db()

        self.assertEqual(act1.status, ActivityStatus.APPROVED)
        self.assertEqual(act1.verified_by, self.tenant_a_admin)
        self.assertTrue(doc1.is_verified)
        self.assertEqual(doc1.verified_by, self.tenant_a_admin)
        self.assertTrue(doc2.is_verified)
        self.assertEqual(doc2.verified_by, self.tenant_a_admin)


class UserProfilePageAndAPITests(TestCase):
    """Automated tests for user profile page and associated API endpoints."""

    def setUp(self):
        import datetime
        from apps.activities.models import AcademicSession, Activity, ActivityType, ActivityStatus
        self.tenant = Tenant.objects.create(name="Apex University", code="APEX", is_active=True)
        self.dept = Department.objects.create(name="Computer Science", code="CS", tenant=self.tenant)
        self.desig = Designation.objects.create(name="Assistant Professor", tenant=self.tenant)
        self.session = AcademicSession.objects.create(
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=True,
            tenant=self.tenant
        )

        self.user = User.objects.create_user(
            username="prof_john",
            email="john@apex.edu",
            password="InitialPassword123!",
            first_name="John",
            last_name="Doe",
            phone="9876543210",
            employee_id="EMP-APEX-001",
            tenant=self.tenant,
            department=self.dept,
            designation=self.desig,
            is_active=True,
            is_approved=True,
        )

        self.supreme = User.objects.create_superuser(
            username="supreme_tester",
            email="supreme@platform.edu",
            password="InitialPassword123!",
        )

        # Create sample activity for stats verification
        self.act = Activity.objects.create(
            tenant=self.tenant,
            faculty=self.user,
            academic_session=self.session,
            title="AI Optimization in Distributed Systems",
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            status=ActivityStatus.APPROVED,
        )

    def test_unauthenticated_profile_redirects_to_login(self):
        """Unauthenticated access to /profile/ must redirect to /admin/login/?next=/profile/."""
        response = self.client.get('/profile/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response.url)
        self.assertIn('next=/profile/', response.url)

    def test_authenticated_faculty_profile_view(self):
        """Faculty user accessing /profile/ sees personal info, department, and activity statistics."""
        self.client.login(username="prof_john", password="InitialPassword123!")
        response = self.client.get('/profile/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn("John Doe", content)
        self.assertIn("Apex University", content)
        self.assertIn("Computer Science", content)
        self.assertIn("AI Optimization in Distributed Systems", content)
        self.assertEqual(response.context['stats']['approved_count'], 1)
        self.assertEqual(response.context['stats']['journals_count'], 1)

    def test_accounts_profile_alias_view(self):
        """Standard Django /accounts/profile/ alias resolves properly."""
        self.client.login(username="prof_john", password="InitialPassword123!")
        response = self.client.get('/accounts/profile/')
        self.assertEqual(response.status_code, 200)

    def test_authenticated_supreme_admin_profile_view(self):
        """Supreme Admin accessing /profile/ sees platform-level metrics."""
        self.client.login(username="supreme_tester", password="InitialPassword123!")
        response = self.client.get('/profile/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn("Platform Supreme Administrator", content)
        self.assertTrue(response.context['is_supreme'])
        self.assertIn('total_tenants', response.context['stats'])

    def test_profile_update_form_submission(self):
        """Submitting update_profile form updates first name, last name, and phone."""
        self.client.login(username="prof_john", password="InitialPassword123!")
        response = self.client.post('/profile/', {
            'form_action': 'update_profile',
            'first_name': 'Jonathan',
            'last_name': 'Doeman',
            'phone': '+91 9998887776',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Jonathan')
        self.assertEqual(self.user.last_name, 'Doeman')
        self.assertEqual(self.user.phone, '+91 9998887776')

    def test_password_change_form_invalid_current_password(self):
        """Submitting wrong current password rejects change."""
        self.client.login(username="prof_john", password="InitialPassword123!")
        response = self.client.post('/profile/', {
            'form_action': 'change_password',
            'current_password': 'WrongPassword123',
            'new_password': 'BrandNewPassword123!',
            'confirm_password': 'BrandNewPassword123!',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('InitialPassword123!'))

    def test_password_change_form_success(self):
        """Submitting valid passwords updates user password and keeps session authenticated."""
        self.client.login(username="prof_john", password="InitialPassword123!")
        response = self.client.post('/profile/', {
            'form_action': 'change_password',
            'current_password': 'InitialPassword123!',
            'new_password': 'BrandNewPassword123!',
            'confirm_password': 'BrandNewPassword123!',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNewPassword123!'))

    def test_api_current_user_patch(self):
        """PATCH /api/accounts/me/ updates profile fields via REST API."""
        from rest_framework.test import APIClient
        api_client = APIClient()
        api_client.force_authenticate(user=self.user)
        response = api_client.patch('/api/accounts/me/', {
            'phone': '9112233445',
            'first_name': 'Johnny',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, '9112233445')
        self.assertEqual(self.user.first_name, 'Johnny')

    def test_api_change_password_endpoint(self):
        """POST /api/accounts/change-password/ validates and updates password via REST API."""
        from rest_framework.test import APIClient
        api_client = APIClient()
        api_client.force_authenticate(user=self.user)

        # Mismatch
        res_mismatch = api_client.post('/api/accounts/change-password/', {
            'current_password': 'InitialPassword123!',
            'new_password': 'BrandNewPassword123!',
            'confirm_password': 'DifferentPassword123!',
        }, format='json')
        self.assertEqual(res_mismatch.status_code, 400)

        # Success
        res_ok = api_client.post('/api/accounts/change-password/', {
            'current_password': 'InitialPassword123!',
            'new_password': 'BrandNewPassword123!',
            'confirm_password': 'BrandNewPassword123!',
        }, format='json')
        self.assertEqual(res_ok.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNewPassword123!'))


class SupremeAdminLoginAndUsernameUniquenessTests(TestCase):
    """Automated tests for Supreme Admin login flows and case-insensitive username uniqueness."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Delta Institute", code="DELTA", is_active=True)
        self.supreme = User.objects.create_superuser(
            username="platform_root",
            email="root@platform.org",
            password="SupremePassword123!",
            tenant=None,
        )
        self.faculty = User.objects.create_user(
            username="faculty_member",
            email="fac@delta.edu",
            password="FacultyPassword123!",
            tenant=self.tenant,
            is_staff=True,
            is_active=True,
            is_approved=True,
        )

    def test_platform_url_is_removed(self):
        """Platform console URL is completely removed and returns 404."""
        response = self.client.get('/platform/')
        self.assertEqual(response.status_code, 404)

    def test_super_admin_manages_tenants_in_django_admin(self):
        """Super admin logs into standard /admin/ and has full tenant management privileges."""
        self.client.login(username='platform_root', password='SupremePassword123!')
        response = self.client.get('/admin/tenants/tenant/')
        self.assertEqual(response.status_code, 200)

    def test_non_staff_faculty_blocked_at_django_admin(self):
        """Non-staff faculty cannot access /admin/."""
        self.faculty.is_staff = False
        self.faculty.save(update_fields=['is_staff'])
        self.client.login(username='faculty_member', password='FacultyPassword123!')
        response = self.client.get('/admin/tenants/tenant/')
        self.assertEqual(response.status_code, 302)

    def test_case_insensitive_username_uniqueness(self):
        """Creating a user with duplicate case-insensitive username must fail."""
        from django.db import IntegrityError
        from django.core.exceptions import ValidationError

        # Model clean() check
        dup_user = User(username='PLATFORM_ROOT', email='other@test.org')
        with self.assertRaises(ValidationError):
            dup_user.clean()

        # Database unique constraint check
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username='PLATFORM_ROOT',
                email='other2@test.org',
                password='SomePassword123!'
            )


    def test_createtenantadmin_rejects_duplicate_username(self):
        """createtenantadmin CLI command rejects duplicate usernames."""
        from django.core.management import call_command, CommandError

        with self.assertRaises(CommandError) as ctx:
            call_command(
                'createtenantadmin',
                tenant='DELTA',
                email='another_admin@delta.edu',
                username='faculty_member',
                password='AdminPassword123!',
                noinput=True,
            )
        self.assertIn("already taken", str(ctx.exception))


class HierarchicalRBACTests(APITestCase):
    """
    Unit and integration tests for Hierarchical Role-Based Access Control (RBAC):
    - Seniority ranks (10-100)
    - Data scoping (organization, department, self)
    - HOD department isolation and seniority guards
    - Role creation sensible defaults
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Apex Institute", code="APEX", is_active=True)
        self.dept_cse = Department.objects.create(tenant=self.tenant, name="Computer Science", code="CSE")
        self.dept_ece = Department.objects.create(tenant=self.tenant, name="Electronics", code="ECE")

        # Modules
        self.mod_accounts = Module.objects.create(name="User Accounts", code="accounts")
        self.mod_activities = Module.objects.create(name="Activities", code="activities")

        # Roles with hierarchy
        self.role_admin = Role.objects.create(
            tenant=self.tenant, name="Organization Admin", code="admin", scope="organization", rank=100
        )
        self.role_dean = Role.objects.create(
            tenant=self.tenant, name="Dean", code="dean", scope="organization", rank=70
        )
        self.role_hod = Role.objects.create(
            tenant=self.tenant, name="HOD", code="hod", scope="department", rank=50
        )
        self.role_coord = Role.objects.create(
            tenant=self.tenant, name="Department Coordinator", code="coordinator", scope="department", rank=30
        )
        self.role_faculty = Role.objects.create(
            tenant=self.tenant, name="Faculty Member", code="faculty", scope="self", rank=10
        )

        # Permissions: grant accounts module access to HOD and Admin
        for role in (self.role_admin, self.role_hod):
            RolePermission.objects.create(
                role=role,
                module=self.mod_accounts,
                can_view=True,
                can_create=True,
                can_edit=True,
                can_delete=True,
            )

        # Grant activities module access to roles
        for role in (self.role_admin, self.role_hod, self.role_coord, self.role_faculty):
            RolePermission.objects.create(
                role=role,
                module=self.mod_activities,
                can_view=True,
                can_create=True,
                can_edit=True,
                can_delete=(role in (self.role_admin, self.role_hod)),
                can_approve=(role in (self.role_admin, self.role_hod, self.role_coord)),
            )

        # Users
        self.admin_user = User.objects.create_user(
            username="apex_admin",
            email="admin@apex.edu",
            password="Password123!",
            tenant=self.tenant,
            role=self.role_admin,
            is_staff=True,
            is_active=True,
            is_approved=True,
        )

        self.hod_cse = User.objects.create_user(
            username="hod_cse",
            email="hod.cse@apex.edu",
            password="Password123!",
            tenant=self.tenant,
            department=self.dept_cse,
            role=self.role_hod,
            is_department_head=True,
            is_active=True,
            is_approved=True,
        )

        self.faculty_cse = User.objects.create_user(
            username="faculty_cse",
            email="fac.cse@apex.edu",
            first_name="Alice",
            last_name="CSE",
            password="Password123!",
            tenant=self.tenant,
            department=self.dept_cse,
            role=self.role_faculty,
            is_active=True,
            is_approved=True,
        )

        self.faculty_ece = User.objects.create_user(
            username="faculty_ece",
            email="fac.ece@apex.edu",
            first_name="Bob",
            last_name="ECE",
            password="Password123!",
            tenant=self.tenant,
            department=self.dept_ece,
            role=self.role_faculty,
            is_active=True,
            is_approved=True,
        )

    def test_role_defaults_assigned_based_on_code(self):
        """Roles automatically populate sensible scope and rank if not explicitly provided."""
        r_hod = Role.objects.create(name="Head of Dept", code="hod")
        self.assertEqual(r_hod.scope, "department")
        self.assertEqual(r_hod.rank, 50)

        r_dean = Role.objects.create(name="Dean of Academics", code="dean")
        self.assertEqual(r_dean.scope, "organization")
        self.assertEqual(r_dean.rank, 70)

        r_admin = Role.objects.create(name="System Admin", code="admin")
        self.assertEqual(r_admin.scope, "organization")
        self.assertEqual(r_admin.rank, 100)

        r_fac = Role.objects.create(name="Assistant Professor", code="faculty")
        self.assertEqual(r_fac.scope, "self")
        self.assertEqual(r_fac.rank, 10)

    def test_hod_scoped_to_own_department_users(self):
        """HOD only sees users belonging to their own department in the user directory."""
        self.client.force_authenticate(user=self.hod_cse)
        response = self.client.get('/api/accounts/users/')
        self.assertEqual(response.status_code, 200)

        usernames = [u['username'] for u in response.data.get('results', response.data)]
        self.assertIn("hod_cse", usernames)
        self.assertIn("faculty_cse", usernames)
        self.assertNotIn("faculty_ece", usernames)

    def test_hod_can_edit_faculty_in_own_department(self):
        """HOD can update information for faculty within their own department."""
        self.client.force_authenticate(user=self.hod_cse)
        response = self.client.patch(
            f'/api/accounts/users/{self.faculty_cse.id}/',
            {'first_name': 'Alicia'},
            format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.faculty_cse.refresh_from_db()
        self.assertEqual(self.faculty_cse.first_name, 'Alicia')

    def test_hod_cannot_edit_faculty_in_another_department(self):
        """HOD cannot edit faculty in another department (blocked by queryset / permissions)."""
        self.client.force_authenticate(user=self.hod_cse)
        response = self.client.patch(
            f'/api/accounts/users/{self.faculty_ece.id}/',
            {'first_name': 'Robert'},
            format='json'
        )
        # Should be 404 (not in queryset) or 403 (permission denied)
        self.assertIn(response.status_code, [403, 404])
        self.faculty_ece.refresh_from_db()
        self.assertEqual(self.faculty_ece.first_name, 'Bob')

    def test_hod_cannot_elevate_faculty_to_equal_or_higher_rank(self):
        """HOD cannot assign a role with rank >= HOD rank (50), such as Dean (70) or Admin (100)."""
        self.client.force_authenticate(user=self.hod_cse)
        response = self.client.patch(
            f'/api/accounts/users/{self.faculty_cse.id}/',
            {'role': str(self.role_dean.id)},
            format='json'
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("seniority rank", str(response.data))

    def test_hod_cannot_transfer_faculty_to_another_department(self):
        """HOD cannot change an employee's department to another department."""
        self.client.force_authenticate(user=self.hod_cse)
        response = self.client.patch(
            f'/api/accounts/users/{self.faculty_cse.id}/',
            {'department': str(self.dept_ece.id)},
            format='json'
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("department", str(response.data).lower())

    def test_admin_has_full_organization_visibility_and_management(self):
        """Organization Admin sees and can manage users across all departments in the tenant."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/accounts/users/')
        self.assertEqual(response.status_code, 200)

        usernames = [u['username'] for u in response.data.get('results', response.data)]
        self.assertIn("faculty_cse", usernames)
        self.assertIn("faculty_ece", usernames)
        self.assertIn("hod_cse", usernames)

        # Admin can update ECE faculty
        patch_res = self.client.patch(
            f'/api/accounts/users/{self.faculty_ece.id}/',
            {'first_name': 'Bobby'},
            format='json'
        )
        self.assertEqual(patch_res.status_code, 200)
        self.faculty_ece.refresh_from_db()
        self.assertEqual(self.faculty_ece.first_name, 'Bobby')

    def test_password_setup_token_not_leaked_in_user_payload(self):
        """password_setup_token is stripped from user serializers to prevent account takeover."""
        self.faculty_cse.password_setup_token = "secret_setup_token_12345"
        self.faculty_cse.save(update_fields=['password_setup_token'])

        self.client.force_authenticate(user=self.admin_user)
        res = self.client.get(f'/api/accounts/users/{self.faculty_cse.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('password_setup_token', res.data)
        self.assertNotIn('password_setup_expires_at', res.data)

        # Also verify CurrentUserView
        self.client.force_authenticate(user=self.faculty_cse)
        me_res = self.client.get('/api/accounts/me/')
        self.assertEqual(me_res.status_code, 200)
        self.assertNotIn('password_setup_token', me_res.data)

    def test_user_summary_masks_sensitive_data_when_can_view_details_is_false(self):
        """User summary masks personal email and phone when viewer has no permission to view details."""
        self.client.force_authenticate(user=self.faculty_cse)
        res = self.client.get('/api/activities/user-summary/')
        self.assertEqual(res.status_code, 200)

        for u in res.data:
            if u['id'] == str(self.faculty_ece.id):
                # Peer from another department without view permissions
                self.assertFalse(u['can_view_details'])
                self.assertNotIn('email', u)
                self.assertNotIn('phone', u)
                self.assertNotIn('employee_id', u)

    def test_bulk_assign_role_blocks_seniority_elevation(self):
        """HOD cannot assign an Admin role to anyone via bulk_assign_role."""
        self.client.force_authenticate(user=self.hod_cse)
        res = self.client.post('/api/accounts/users/bulk-assign-role/', {
            'user_ids': [str(self.faculty_cse.id)],
            'role_id': str(self.role_admin.id)
        }, format='json')
        self.assertEqual(res.status_code, 403)
        self.assertIn("seniority rank", str(res.data))

    def test_bulk_assign_role_blocks_cross_department_assignment(self):
        """HOD cannot reassign roles for faculty outside their department."""
        self.client.force_authenticate(user=self.hod_cse)
        res = self.client.post('/api/accounts/users/bulk-assign-role/', {
            'user_ids': [str(self.faculty_ece.id)],
            'role_id': str(self.role_coord.id)
        }, format='json')
        self.assertEqual(res.status_code, 403)
        self.assertIn("department", str(res.data).lower())

    def test_hod_cannot_create_or_delete_institutional_roles(self):
        """Role management is restricted strictly to Organization Administrators."""
        self.client.force_authenticate(user=self.hod_cse)
        res = self.client.post('/api/accounts/roles/', {
            'name': 'Hacked Role',
            'code': 'hacked',
            'rank': 100,
            'scope': 'organization'
        }, format='json')
        self.assertEqual(res.status_code, 403)

    def test_draft_activity_not_accessible_by_other_faculty_or_cross_dept(self):
        """Draft activities can strictly only be retrieved by the author/co-author."""
        from apps.activities.models import Activity, ActivityType, ActivityStatus, AcademicSession
        session = AcademicSession.objects.create(tenant=self.tenant, name="2025-2026", start_date="2025-07-01", end_date="2026-06-30")
        draft = Activity.objects.create(
            tenant=self.tenant,
            faculty=self.faculty_cse,
            academic_session=session,
            title="Unpublished Secret Draft",
            activity_type=ActivityType.PATENT,
            status=ActivityStatus.DRAFT
        )

        # Author can view
        self.client.force_authenticate(user=self.faculty_cse)
        res_author = self.client.get(f'/api/activities/{draft.id}/')
        self.assertEqual(res_author.status_code, 200)

        # Faculty from another department cannot view (403 Forbidden)
        self.client.force_authenticate(user=self.faculty_ece)
        res_peer = self.client.get(f'/api/activities/{draft.id}/')
        self.assertEqual(res_peer.status_code, 403)

        # HOD from another department cannot view (403 Forbidden)
        dept_ece_hod = User.objects.create_user(
            username="hod_ece", email="hod.ece@apex.edu", password="pw",
            tenant=self.tenant, department=self.dept_ece, role=self.role_hod, is_department_head=True
        )
        self.client.force_authenticate(user=dept_ece_hod)
        res_cross_hod = self.client.get(f'/api/activities/{draft.id}/')
        self.assertEqual(res_cross_hod.status_code, 403)

    def test_faculty_view_departments_returns_own_department_not_403(self):
        """
        Faculty querying /api/accounts/departments/ receives 200 OK showing their own department
        instead of receiving 403 Forbidden.
        """
        self.client.force_authenticate(user=self.faculty_cse)
        res = self.client.get('/api/accounts/departments/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], str(self.dept_cse.id))
        self.assertEqual(results[0]['code'], self.dept_cse.code)

    def test_faculty_cannot_view_other_department_detail(self):
        """Faculty cannot retrieve other departments' detail views (returns 404)."""
        self.client.force_authenticate(user=self.faculty_cse)
        res = self.client.get(f'/api/accounts/departments/{self.dept_ece.id}/')
        self.assertEqual(res.status_code, 404)

        # But can retrieve their own department
        res_own = self.client.get(f'/api/accounts/departments/{self.dept_cse.id}/')
        self.assertEqual(res_own.status_code, 200)

    def test_faculty_cannot_create_or_modify_departments(self):
        """Faculty cannot mutate departments (403 Forbidden)."""
        self.client.force_authenticate(user=self.faculty_cse)
        res = self.client.post('/api/accounts/departments/', {
            'name': 'Hacked Department',
            'code': 'HACK'
        }, format='json')
        self.assertEqual(res.status_code, 403)

    def test_org_admin_sees_all_departments(self):
        """Org Admin sees all departments in the tenant."""
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.get('/api/accounts/departments/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        results = data.get('results', data) if isinstance(data, dict) else data
        dept_ids = [d['id'] for d in results]
        self.assertIn(str(self.dept_cse.id), dept_ids)
        self.assertIn(str(self.dept_ece.id), dept_ids)





