import datetime
from django.test import TestCase
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

import io
import openpyxl
from apps.tenants.models import Tenant
from apps.tenants.permissions import is_supreme_admin
from apps.activities.models import AcademicSession, Activity, ActivityType, ActivityStatus
from apps.accounts.models import Department, Designation, Role, RolePermission, Module
from apps.activities.admin import AcademicSessionAdmin, ActivityAdmin
from apps.accounts.admin import UserAdmin, DepartmentAdmin, DesignationAdmin
from apps.tenants.admin import TenantAdmin
from django.contrib.admin.sites import AdminSite

from django.test import RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware

User = get_user_model()


class MockRequest:
    def __init__(self, user):
        self.user = user


class AcademicSessionAtomicCurrentTests(TestCase):
    """
    Tests ensuring that strictly ONE current session exists per tenant at any given time,
    and that switching current sessions automatically deactivates other sessions atomically.
    """

    def setUp(self):
        self.tenant_a = Tenant.objects.create(
            name="Alpha Institute",
            code="ALPHA",
            slug="alpha-inst",
            is_active=True
        )
        self.tenant_b = Tenant.objects.create(
            name="Beta University",
            code="BETA",
            slug="beta-univ",
            is_active=True
        )

    def test_single_current_session_enforced_on_creation(self):
        """When a new session is created as current, prior current sessions are deactivated."""
        sess_1 = AcademicSession.objects.create(
            tenant=self.tenant_a,
            name="2024-2025",
            start_date=datetime.date(2024, 7, 1),
            end_date=datetime.date(2025, 6, 30),
            is_current=True
        )
        self.assertTrue(sess_1.is_current)

        # Create session 2 as current
        sess_2 = AcademicSession.objects.create(
            tenant=self.tenant_a,
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=True
        )
        sess_1.refresh_from_db()
        sess_2.refresh_from_db()

        self.assertFalse(sess_1.is_current)
        self.assertTrue(sess_2.is_current)

        # Exactly 1 current session for tenant_a
        current_count = AcademicSession.objects.filter(tenant=self.tenant_a, is_current=True).count()
        self.assertEqual(current_count, 1)

    def test_atomic_switch_when_updating_existing_session(self):
        """Updating an existing session's is_current to True deactivates other sessions for that tenant."""
        sess_1 = AcademicSession.objects.create(
            tenant=self.tenant_a,
            name="2024-2025",
            start_date=datetime.date(2024, 7, 1),
            end_date=datetime.date(2025, 6, 30),
            is_current=True
        )
        sess_2 = AcademicSession.objects.create(
            tenant=self.tenant_a,
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=False
        )

        self.assertTrue(sess_1.is_current)
        self.assertFalse(sess_2.is_current)

        # Now mark sess_2 as current
        sess_2.is_current = True
        sess_2.save()

        sess_1.refresh_from_db()
        sess_2.refresh_from_db()

        self.assertFalse(sess_1.is_current)
        self.assertTrue(sess_2.is_current)

    def test_cross_tenant_session_isolation(self):
        """Setting a session as current in Tenant B does NOT alter Tenant A's current session."""
        sess_a1 = AcademicSession.objects.create(
            tenant=self.tenant_a,
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=True
        )
        sess_b1 = AcademicSession.objects.create(
            tenant=self.tenant_b,
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=True
        )

        # Both tenants have their own 1 active session
        self.assertTrue(sess_a1.is_current)
        self.assertTrue(sess_b1.is_current)

        # Create new current session in Tenant B
        sess_b2 = AcademicSession.objects.create(
            tenant=self.tenant_b,
            name="2026-2027",
            start_date=datetime.date(2026, 7, 1),
            end_date=datetime.date(2027, 6, 30),
            is_current=True
        )

        sess_a1.refresh_from_db()
        sess_b1.refresh_from_db()
        sess_b2.refresh_from_db()

        # Tenant A's current session must STILL be True!
        self.assertTrue(sess_a1.is_current)
        # Tenant B's old session is False, new is True
        self.assertFalse(sess_b1.is_current)
        self.assertTrue(sess_b2.is_current)

    def test_session_name_uniqueness_scoped_to_tenant(self):
        """Session names can be identical across different tenants, but must be unique within a tenant."""
        AcademicSession.objects.create(
            tenant=self.tenant_a,
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=True
        )
        # Same name in Tenant B is completely valid
        sess_b = AcademicSession.objects.create(
            tenant=self.tenant_b,
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=True
        )
        self.assertIsNotNone(sess_b.id)

        # Duplicate name in same tenant must raise IntegrityError
        with self.assertRaises(IntegrityError):
            AcademicSession.objects.create(
                tenant=self.tenant_a,
                name="2025-2026",
                start_date=datetime.date(2025, 7, 1),
                end_date=datetime.date(2026, 6, 30),
                is_current=False
            )

    def test_admin_mark_as_current_action(self):
        """Test AcademicSessionAdmin mark_session_as_current action."""
        sess_1 = AcademicSession.objects.create(
            tenant=self.tenant_a,
            name="2024-2025",
            start_date=datetime.date(2024, 7, 1),
            end_date=datetime.date(2025, 6, 30),
            is_current=True
        )
        sess_2 = AcademicSession.objects.create(
            tenant=self.tenant_a,
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=False
        )

        admin = AcademicSessionAdmin(AcademicSession, AdminSite())
        user = User.objects.create_superuser(username="admin_test", password="pw")
        factory = RequestFactory()
        request = factory.get('/')
        request.user = user
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        messages_storage = FallbackStorage(request)
        setattr(request, '_messages', messages_storage)

        # Call action on sess_2
        qs = AcademicSession.objects.filter(pk=sess_2.pk)
        admin.mark_session_as_current(request, qs)

        sess_1.refresh_from_db()
        sess_2.refresh_from_db()
        self.assertFalse(sess_1.is_current)
        self.assertTrue(sess_2.is_current)


class SupremeAdminAndTenantIsolationAPITests(APITestCase):
    """
    API tests verifying Supreme Admin permissions, tenant lifecycle actions,
    and cross-tenant data isolation.
    """

    def setUp(self):
        # Create Tenants
        self.tenant_a = Tenant.objects.create(
            name="Alpha University",
            code="ALPHA",
            slug="alpha-u",
            is_active=True
        )
        self.tenant_b = Tenant.objects.create(
            name="Beta Institute",
            code="BETA",
            slug="beta-i",
            is_active=True
        )

        # Create Roles
        self.faculty_role = Role.objects.create(name="Faculty Member", code="faculty")
        self.mod_activities = Module.objects.create(name="Activities", code="activities")
        RolePermission.objects.create(
            role=self.faculty_role,
            module=self.mod_activities,
            can_view=True,
            can_create=True,
            can_edit=True,
            can_export=True
        )

        # Super Admin (platform owner, not bound to tenant)
        self.supreme_admin = User.objects.create_superuser(
            username="supreme_owner",
            password="pw",
            tenant=None
        )

        # Tenant A Users
        self.dept_a = Department.objects.create(tenant=self.tenant_a, name="Computer Science A", code="CSA")
        self.faculty_a = User.objects.create_user(
            username="prof.alpha",
            password="pw",
            first_name="Alpha",
            last_name="Prof",
            tenant=self.tenant_a,
            department=self.dept_a,
            role=self.faculty_role
        )

        # Tenant B Users
        self.dept_b = Department.objects.create(tenant=self.tenant_b, name="Computer Science B", code="CSB")
        self.faculty_b = User.objects.create_user(
            username="prof.beta",
            password="pw",
            first_name="Beta",
            last_name="Prof",
            tenant=self.tenant_b,
            department=self.dept_b,
            role=self.faculty_role
        )

        # Sessions
        self.session_a = AcademicSession.objects.create(
            tenant=self.tenant_a,
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=True
        )
        self.session_b = AcademicSession.objects.create(
            tenant=self.tenant_b,
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=True
        )

        # Activities
        self.act_a = Activity.objects.create(
            tenant=self.tenant_a,
            faculty=self.faculty_a,
            academic_session=self.session_a,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Quantum Research in Alpha",
            status=ActivityStatus.SUBMITTED
        )
        self.act_b = Activity.objects.create(
            tenant=self.tenant_b,
            faculty=self.faculty_b,
            academic_session=self.session_b,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Neural Architectures in Beta",
            status=ActivityStatus.SUBMITTED
        )

    def test_supreme_admin_permissions_helper(self):
        """Verify is_supreme_admin helper accurately distinguishes platform owner."""
        req_supreme = MockRequest(self.supreme_admin)
        self.assertTrue(is_supreme_admin(req_supreme))

        req_faculty_a = MockRequest(self.faculty_a)
        self.assertFalse(is_supreme_admin(req_faculty_a))

    def test_supreme_admin_can_manage_tenants_endpoint(self):
        """Only Supreme Admin can query and manage /api/tenants/."""
        self.client.force_authenticate(user=self.supreme_admin)
        res = self.client.get('/api/tenants/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Deactivate Tenant B
        deact_res = self.client.post(f'/api/tenants/{self.tenant_b.id}/deactivate/')
        self.assertEqual(deact_res.status_code, status.HTTP_200_OK)
        self.tenant_b.refresh_from_db()
        self.assertFalse(self.tenant_b.is_active)

    def test_regular_user_cannot_access_tenants_endpoint(self):
        """Non-supreme users are forbidden from /api/tenants/."""
        self.client.force_authenticate(user=self.faculty_a)
        res = self.client.get('/api/tenants/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_deactivated_tenant_user_is_blocked_from_all_endpoints(self):
        """When a tenant is deactivated, all of its users receive 403 on API requests."""
        self.tenant_a.is_active = False
        self.tenant_a.save()

        self.client.force_authenticate(user=self.faculty_a)
        res = self.client.get('/api/activities/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("inactive or suspended", str(res.data))

    def test_cross_tenant_activity_isolation(self):
        """Faculty A only sees Activity A; Faculty B only sees Activity B."""
        self.client.force_authenticate(user=self.faculty_a)
        res_a = self.client.get('/api/activities/')
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)
        titles_a = [item['title'] for item in res_a.data.get('results', res_a.data)]
        self.assertIn("Quantum Research in Alpha", titles_a)
        self.assertNotIn("Neural Architectures in Beta", titles_a)

        self.client.force_authenticate(user=self.faculty_b)
        res_b = self.client.get('/api/activities/')
        self.assertEqual(res_b.status_code, status.HTTP_200_OK)
        titles_b = [item['title'] for item in res_b.data.get('results', res_b.data)]
        self.assertIn("Neural Architectures in Beta", titles_b)
        self.assertNotIn("Quantum Research in Alpha", titles_b)

    def test_supreme_admin_sees_all_tenant_activities(self):
        """Supreme admin sees activities across all tenants."""
        self.client.force_authenticate(user=self.supreme_admin)
        res = self.client.get('/api/activities/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        titles = [item['title'] for item in res.data.get('results', res.data)]
        self.assertIn("Quantum Research in Alpha", titles)
        self.assertIn("Neural Architectures in Beta", titles)

    def test_current_user_endpoint_exposes_tenant_details(self):
        """GET /api/accounts/me/ returns tenant object and is_superuser flag."""
        self.client.force_authenticate(user=self.faculty_a)
        res = self.client.get('/api/accounts/me/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data.get('is_superuser', False))
        self.assertIsNotNone(res.data['tenant'])
        self.assertEqual(res.data['tenant']['code'], "ALPHA")

        self.client.force_authenticate(user=self.supreme_admin)
        res_sup = self.client.get('/api/accounts/me/')
        self.assertEqual(res_sup.status_code, status.HTTP_200_OK)
        self.assertTrue(res_sup.data.get('is_superuser', False))
        self.assertIsNone(res_sup.data['tenant'])


class TenantAdminExplicitIsolationTests(APITestCase):
    """
    Exhaustive tests verifying that a Tenant Admin (administrator scoped to Tenant A)
    can ONLY access and see Tenant A's data, and NEVER Tenant B's data across:
    1. REST API Activity listings
    2. REST API User directory
    3. REST API Department listings
    4. REST API Academic Sessions
    5. REST API NAAC Criteria 3 Reports/Exports
    6. Admin Panel QuerySets (ActivityAdmin, UserAdmin, DepartmentAdmin, AcademicSessionAdmin)
    7. Admin Panel Permissions (TenantAdmin.has_module_permission -> False)
    8. Security guards preventing Tenant Admin from elevating privileges to supreme admin.
    """

    def setUp(self):
        # Create Tenants
        self.tenant_a = Tenant.objects.create(name="Tenant Alpha", code="TA", slug="tenant-a", is_active=True)
        self.tenant_b = Tenant.objects.create(name="Tenant Beta", code="TB", slug="tenant-b", is_active=True)

        # Create Roles
        self.super_admin_role = Role.objects.create(name="Super Administrator", code="super_admin")
        self.faculty_role = Role.objects.create(name="Faculty Member", code="faculty")

        # Create Modules
        self.mod_activities = Module.objects.create(name="Activities", code="activities")
        self.mod_reports = Module.objects.create(name="Reports", code="reports")
        self.mod_accounts = Module.objects.create(name="Accounts", code="accounts")

        for mod in (self.mod_activities, self.mod_reports, self.mod_accounts):
            RolePermission.objects.create(
                role=self.super_admin_role,
                module=mod,
                can_view=True,
                can_create=True,
                can_edit=True,
                can_delete=True,
                can_approve=True,
                can_export=True
            )

        # Tenant A Admin (is_staff=True, tenant=tenant_a)
        self.tenant_a_admin = User.objects.create_user(
            username="admin.alpha",
            password="pw",
            first_name="Admin",
            last_name="Alpha",
            tenant=self.tenant_a,
            is_staff=True,
            role=self.super_admin_role
        )

        # Tenant B Admin (is_staff=True, tenant=tenant_b)
        self.tenant_b_admin = User.objects.create_user(
            username="admin.beta",
            password="pw",
            first_name="Admin",
            last_name="Beta",
            tenant=self.tenant_b,
            is_staff=True,
            role=self.super_admin_role
        )

        # Tenant A Department & Faculty
        self.dept_a = Department.objects.create(tenant=self.tenant_a, name="Computer Science Alpha", code="CSA")
        self.faculty_a = User.objects.create_user(
            username="faculty.alpha",
            password="pw",
            first_name="Fac",
            last_name="Alpha",
            tenant=self.tenant_a,
            department=self.dept_a,
            role=self.faculty_role
        )

        # Tenant B Department & Faculty
        self.dept_b = Department.objects.create(tenant=self.tenant_b, name="Mechanical Beta", code="MEB")
        self.faculty_b = User.objects.create_user(
            username="faculty.beta",
            password="pw",
            first_name="Fac",
            last_name="Beta",
            tenant=self.tenant_b,
            department=self.dept_b,
            role=self.faculty_role
        )

        # Academic Sessions
        self.sess_a = AcademicSession.objects.create(
            tenant=self.tenant_a,
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=True
        )
        self.sess_b = AcademicSession.objects.create(
            tenant=self.tenant_b,
            name="2025-2026",
            start_date=datetime.date(2025, 7, 1),
            end_date=datetime.date(2026, 6, 30),
            is_current=True
        )

        # Activities
        self.act_a = Activity.objects.create(
            tenant=self.tenant_a,
            faculty=self.faculty_a,
            academic_session=self.sess_a,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Alpha Breakthrough Paper",
            status=ActivityStatus.APPROVED
        )
        self.act_b = Activity.objects.create(
            tenant=self.tenant_b,
            faculty=self.faculty_b,
            academic_session=self.sess_b,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Beta Autonomous Driving",
            status=ActivityStatus.APPROVED
        )

    def test_tenant_admin_only_sees_their_tenant_activities_api(self):
        """Tenant A admin sees all Tenant A activities, but ZERO Tenant B activities."""
        self.client.force_authenticate(user=self.tenant_a_admin)
        res = self.client.get('/api/activities/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        titles = [item['title'] for item in res.data.get('results', res.data)]
        self.assertIn("Alpha Breakthrough Paper", titles)
        self.assertNotIn("Beta Autonomous Driving", titles)

    def test_tenant_admin_only_sees_their_tenant_users_api(self):
        """Tenant A admin sees Tenant A users, but ZERO Tenant B users."""
        self.client.force_authenticate(user=self.tenant_a_admin)
        res = self.client.get('/api/accounts/users/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        usernames = [u['username'] for u in res.data.get('results', res.data)]
        self.assertIn("admin.alpha", usernames)
        self.assertIn("faculty.alpha", usernames)
        self.assertNotIn("admin.beta", usernames)
        self.assertNotIn("faculty.beta", usernames)

    def test_tenant_admin_only_sees_their_tenant_departments_api(self):
        """Tenant A admin sees Tenant A departments, but ZERO Tenant B departments."""
        self.client.force_authenticate(user=self.tenant_a_admin)
        res = self.client.get('/api/accounts/departments/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        codes = [d['code'] for d in res.data.get('results', res.data)]
        self.assertIn("CSA", codes)
        self.assertNotIn("MEB", codes)

    def test_tenant_admin_only_sees_their_tenant_sessions_api(self):
        """Tenant A admin sees Tenant A academic sessions, but ZERO Tenant B sessions."""
        self.client.force_authenticate(user=self.tenant_a_admin)
        res = self.client.get('/api/sessions/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        session_ids = [str(s['id']) for s in res.data.get('results', res.data)]
        self.assertIn(str(self.sess_a.id), session_ids)
        self.assertNotIn(str(self.sess_b.id), session_ids)

    def test_tenant_admin_naac_export_strictly_isolated(self):
        """Tenant A admin NAAC export only contains Tenant A records, never Tenant B records."""
        self.client.force_authenticate(user=self.tenant_a_admin)
        res = self.client.get('/api/activities/export/?status=all')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Inspect generated workbook
        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        sheet = wb['NAAC 3.4.3 (Journals)']
        all_cell_values = []
        for row in sheet.iter_rows(values_only=True):
            for cell in row:
                if cell:
                    all_cell_values.append(str(cell))

        # Alpha paper is present
        self.assertTrue(any("Alpha Breakthrough Paper" in val for val in all_cell_values))
        # Beta paper is strictly absent!
        self.assertFalse(any("Beta Autonomous Driving" in val for val in all_cell_values))

    def test_tenant_admin_cannot_access_or_manage_tenants_api(self):
        """Tenant Admin cannot access tenant list or execute activation/deactivation."""
        self.client.force_authenticate(user=self.tenant_a_admin)
        res = self.client.get('/api/tenants/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        res_post = self.client.post(f'/api/tenants/{self.tenant_b.id}/deactivate/')
        self.assertEqual(res_post.status_code, status.HTTP_403_FORBIDDEN)

    def test_tenant_admin_unfold_admin_querysets_strictly_scoped(self):
        """Django Admin querysets for Tenant Admin are strictly scoped to their tenant."""
        request = MockRequest(self.tenant_a_admin)

        site = AdminSite()
        # ActivityAdmin
        act_admin = ActivityAdmin(Activity, site)
        act_qs = act_admin.get_queryset(request)
        self.assertIn(self.act_a, act_qs)
        self.assertNotIn(self.act_b, act_qs)

        # UserAdmin
        user_admin = UserAdmin(User, site)
        user_qs = user_admin.get_queryset(request)
        self.assertIn(self.faculty_a, user_qs)
        self.assertNotIn(self.faculty_b, user_qs)

        # DepartmentAdmin
        dept_admin = DepartmentAdmin(Department, site)
        dept_qs = dept_admin.get_queryset(request)
        self.assertIn(self.dept_a, dept_qs)
        self.assertNotIn(self.dept_b, dept_qs)

        # AcademicSessionAdmin
        sess_admin = AcademicSessionAdmin(AcademicSession, site)
        sess_qs = sess_admin.get_queryset(request)
        self.assertIn(self.sess_a, sess_qs)
        self.assertNotIn(self.sess_b, sess_qs)

        # TenantAdmin has_module_permission is FALSE for Tenant Admin
        tenant_admin = TenantAdmin(Tenant, site)
        self.assertFalse(tenant_admin.has_module_permission(request))

    def test_tenant_admin_cannot_elevate_users_in_admin_panel(self):
        """Tenant Admin cannot elevate any user to Superuser or reassign to another tenant."""
        request = MockRequest(self.tenant_a_admin)
        site = AdminSite()
        user_admin = UserAdmin(User, site)

        new_user = User(
            username="sneaky_user",
            first_name="Sneaky",
            last_name="User",
            email="sneaky@test.com",
            is_superuser=True,  # Attempting elevation
            tenant=self.tenant_b     # Attempting cross-tenant assignment
        )
        user_admin.save_model(request, new_user, form=None, change=False)
        new_user.refresh_from_db()

        # The system must have stripped superuser and locked user to tenant_a!
        self.assertFalse(new_user.is_superuser)
        self.assertEqual(new_user.tenant_id, self.tenant_a.id)

    def test_public_organization_registration_and_approval_flow(self):
        """Public users can submit an organization registration application which starts pending until Supreme Admin approves."""
        # 1. GET registration page returns 200
        get_res = self.client.get('/register-organization/')
        self.assertEqual(get_res.status_code, status.HTTP_200_OK)
        self.assertIn("Register Your Organization", get_res.content.decode('utf-8'))

        # 2. POST registration form data
        reg_payload = {
            "name": "Zenith Technical University",
            "code": "ZTU",
            "domain": "ztu.edu.in",
            "subscription_tier": "standard",
            "admin_first_name": "Vikram",
            "admin_last_name": "Singh",
            "admin_email": "registrar@ztu.edu.in",
            "admin_phone": "9876543210",
            "admin_password": "ZenithPassword123!",
            "confirm_password": "ZenithPassword123!",
        }
        post_res = self.client.post('/api/tenants/register/', reg_payload, format='json')
        self.assertEqual(post_res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(post_res.data['success'])

        # 3. Verify created in pending state
        tenant = Tenant.objects.get(code="ZTU")
        self.assertFalse(tenant.is_active)  # Inactive pending Supreme Admin approval

        overseer = User.objects.get(email="registrar@ztu.edu.in")
        self.assertFalse(overseer.is_active)
        self.assertFalse(overseer.is_approved)
        self.assertEqual(overseer.tenant, tenant)
        self.assertTrue(overseer.check_password("ZenithPassword123!"))

        # 4. Super Admin activates the tenant
        supreme_admin = User.objects.create_superuser(
            username="sup_reg_test",
            email="sup_reg@platform.org",
            password="pw",
            tenant=None
        )
        self.client.force_authenticate(user=supreme_admin)
        act_res = self.client.post(f'/api/tenants/{tenant.id}/activate/')
        self.assertEqual(act_res.status_code, status.HTTP_200_OK)

        tenant.refresh_from_db()
        overseer.refresh_from_db()
        self.assertTrue(tenant.is_active)
        self.assertTrue(overseer.is_active)
        self.assertTrue(overseer.is_approved)


