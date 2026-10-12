import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import User, Department, Designation, Role, Module, RolePermission
from apps.activities.models import AcademicSession, Activity, ActivityAuthor, ActivityStatus, ActivityType
from apps.documents.models import ActivityDocument, DocumentType


class ActivityBaseTestCase(TestCase):
    def setUp(self):
        # Create Departments
        self.dept_cs = Department.objects.create(name="Computer Science & Engineering", code="CSE")
        self.dept_ai = Department.objects.create(name="Artificial Intelligence & Data Science", code="AIDS")

        # Create Designations
        self.desig_prof = Designation.objects.create(name="Professor", code="PROF", priority=10)
        self.desig_ap = Designation.objects.create(name="Assistant Professor", code="AP", priority=30)

        # Create Roles
        self.role_admin = Role.objects.create(name="Super Admin", code="super_admin")
        self.role_hod = Role.objects.create(name="Head of Department", code="hod")
        self.role_coord = Role.objects.create(name="Department Coordinator", code="coordinator")
        self.role_faculty = Role.objects.create(name="Faculty Member", code="faculty")

        # Create Users
        self.admin_user = User.objects.create_superuser(
            username="admin_user",
            email="admin@poornima.org",
            password="password123",
            first_name="Admin",
            last_name="User"
        )

        self.coordinator_cs = User.objects.create_user(
            username="coord_cs",
            email="coord.cs@poornima.org",
            password="password123",
            first_name="CS",
            last_name="Coordinator",
            employee_id="COORD001",
            department=self.dept_cs,
            designation=self.desig_ap,
            role=self.role_coord,
            is_coordinator=True,
            is_staff=True
        )

        self.faculty_cs_1 = User.objects.create_user(
            username="fac_cs_1",
            email="fac1.cs@poornima.org",
            password="password123",
            first_name="Rahul",
            last_name="Sharma",
            employee_id="FAC001",
            department=self.dept_cs,
            designation=self.desig_ap,
            role=self.role_faculty
        )

        self.faculty_cs_2 = User.objects.create_user(
            username="fac_cs_2",
            email="fac2.cs@poornima.org",
            password="password123",
            first_name="Priya",
            last_name="Verma",
            employee_id="FAC002",
            department=self.dept_cs,
            designation=self.desig_ap,
            role=self.role_faculty
        )

        self.faculty_ai = User.objects.create_user(
            username="fac_ai_1",
            email="fac1.ai@poornima.org",
            password="password123",
            first_name="Amit",
            last_name="Kumar",
            employee_id="FAC003",
            department=self.dept_ai,
            designation=self.desig_prof,
            role=self.role_faculty
        )

        # Academic Session
        self.session = AcademicSession.objects.create(
            name="2025-2026",
            start_date="2025-07-01",
            end_date="2026-06-30",
            is_current=True
        )

        # Seed RBAC Modules and RolePermissions
        self.mod_activities = Module.objects.create(name="Activities", code="activities")
        self.mod_documents = Module.objects.create(name="Documents", code="documents")
        self.mod_accounts = Module.objects.create(name="Accounts", code="accounts")

        for role in [self.role_admin, self.role_hod, self.role_coord, self.role_faculty]:
            RolePermission.objects.create(
                role=role,
                module=self.mod_activities,
                can_view=True,
                can_create=True,
                can_edit=True,
                can_delete=(role != self.role_faculty),
                can_approve=(role in (self.role_admin, self.role_hod, self.role_coord)),
                can_export=(role in (self.role_admin, self.role_hod, self.role_coord)),
            )
            RolePermission.objects.create(
                role=role,
                module=self.mod_documents,
                can_view=True,
                can_create=True,
                can_edit=True,
                can_delete=(role != self.role_faculty),
                can_approve=(role in (self.role_admin, self.role_hod, self.role_coord)),
                can_export=(role in (self.role_admin, self.role_hod, self.role_coord)),
            )
            RolePermission.objects.create(
                role=role,
                module=self.mod_accounts,
                can_view=True,
                can_create=(role in (self.role_admin, self.role_hod)),
                can_edit=(role in (self.role_admin, self.role_hod)),
                can_delete=False,
                can_approve=False,
                can_export=False,
            )

        self.client = APIClient()


class ActivityModelAndWorkflowTests(ActivityBaseTestCase):
    def test_activity_creation_and_has_proof_property(self):
        activity = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Deep Learning Frameworks for Medical Imaging",
            status=ActivityStatus.DRAFT,
            metadata={"journal_name": "IEEE Access", "impact_factor": 3.9}
        )
        self.assertEqual(str(activity), f"[Journal Publication] Deep Learning Frameworks for Medical Imaging ({self.faculty_cs_1.display_name})")
        self.assertFalse(activity.has_proof)

        # Attach a dummy proof document
        dummy_file = SimpleUploadedFile("paper_reprint.pdf", b"%PDF-1.4 dummy content", content_type="application/pdf")
        doc = ActivityDocument.objects.create(
            activity=activity,
            document_type=DocumentType.PUBLISHED_PAPER,
            title="Reprint Proof",
            file=dummy_file
        )
        self.assertTrue(activity.has_proof)
        self.assertEqual(activity.documents.count(), 1)
        self.assertTrue(doc.is_pdf)
        self.assertFalse(doc.is_image)

    def test_faculty_can_submit_draft_activity(self):
        self.client.force_authenticate(user=self.faculty_cs_1)
        activity = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.CONFERENCE_PUBLICATION,
            title="Quantum Optimization on Grid Networks",
            status=ActivityStatus.DRAFT
        )

        # Submit for review
        url = f"/api/activities/{activity.id}/submit/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        activity.refresh_from_db()
        self.assertEqual(activity.status, ActivityStatus.SUBMITTED)

        # Submitting again should be rejected with 400
        response2 = self.client.post(url)
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only draft activities can be submitted", response2.data["error"])

    def test_approval_strictly_blocked_without_proof_documents(self):
        """CRITICAL INVARIANT: Zero-proof activities must never be approved."""
        self.client.force_authenticate(user=self.coordinator_cs)
        activity = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.PATENT,
            title="Smart Water Purification System and Method",
            status=ActivityStatus.SUBMITTED
        )

        url = f"/api/activities/{activity.id}/approve/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cannot approve", response.data["error"])
        self.assertIn("at least one verified proof", response.data["error"])

        activity.refresh_from_db()
        self.assertEqual(activity.status, ActivityStatus.SUBMITTED)

    def test_approval_succeeds_when_proof_is_attached(self):
        self.client.force_authenticate(user=self.coordinator_cs)
        activity = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.PATENT,
            title="Smart Water Purification System and Method",
            status=ActivityStatus.SUBMITTED
        )

        dummy_pdf = SimpleUploadedFile("patent_gazette.pdf", b"%PDF-1.4 gazette content", content_type="application/pdf")
        ActivityDocument.objects.create(
            activity=activity,
            document_type=DocumentType.PATENT_GRANT_CERTIFICATE,
            title="Official Gazette Notification",
            file=dummy_pdf
        )

        url = f"/api/activities/{activity.id}/approve/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "approved")

        activity.refresh_from_db()
        self.assertEqual(activity.status, ActivityStatus.APPROVED)
        self.assertEqual(activity.verified_by, self.coordinator_cs)
        self.assertIsNotNone(activity.verified_at)

    def test_faculty_cannot_approve_activities(self):
        """Role isolation: Regular faculty cannot approve any activity."""
        # Case 1: Faculty attempting to access another faculty's activity gets 404 (queryset scoping)
        self.client.force_authenticate(user=self.faculty_cs_2)
        activity = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Edge Computing in Healthcare",
            status=ActivityStatus.SUBMITTED
        )
        url = f"/api/activities/{activity.id}/approve/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Case 2: Faculty attempting to approve their own activity gets 403 (permission check)
        self.client.force_authenticate(user=self.faculty_cs_1)
        response_own = self.client.post(url)
        self.assertEqual(response_own.status_code, status.HTTP_403_FORBIDDEN)

    def test_rejection_requires_non_empty_reason(self):
        self.client.force_authenticate(user=self.coordinator_cs)
        activity = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.FACULTY_PARTICIPATION,
            title="ATAL FDP on Cloud Security",
            status=ActivityStatus.SUBMITTED
        )

        # Empty reason rejected
        url = f"/api/activities/{activity.id}/reject/"
        response = self.client.post(url, {"reason": "   "}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non-empty 'reason' is required", response.data["error"])

        # Non-empty reason succeeds
        response2 = self.client.post(url, {"reason": "Certificate image is blurry and missing dates."}, format='json')
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.data["status"], "rejected")

        activity.refresh_from_db()
        self.assertEqual(activity.status, ActivityStatus.REJECTED)
        self.assertEqual(activity.rejection_reason, "Certificate image is blurry and missing dates.")
        self.assertEqual(activity.verified_by, self.coordinator_cs)


class DepartmentScopingAndPeerMetricsTests(ActivityBaseTestCase):
    def setUp(self):
        super().setUp()
        # Create activities for CS faculty 1
        Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="CS1 Journal Article",
            status=ActivityStatus.APPROVED
        )
        Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.CONFERENCE_PUBLICATION,
            title="CS1 Conference Paper",
            status=ActivityStatus.APPROVED
        )

        # Create activity for CS faculty 2
        Activity.objects.create(
            faculty=self.faculty_cs_2,
            academic_session=self.session,
            activity_type=ActivityType.PATENT,
            title="CS2 Patent Filing",
            status=ActivityStatus.SUBMITTED
        )

        # Create activity for AI faculty
        Activity.objects.create(
            faculty=self.faculty_ai,
            academic_session=self.session,
            activity_type=ActivityType.FACULTY_PARTICIPATION,
            title="AI Faculty FDP",
            status=ActivityStatus.APPROVED
        )

    def test_department_scoping_on_activity_list(self):
        # 1. Faculty member sees only own activities
        self.client.force_authenticate(user=self.faculty_cs_1)
        res = self.client.get("/api/activities/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data.get("results", res.data)
        self.assertEqual(len(data), 2)
        for item in data:
            self.assertEqual(str(item["faculty"]), str(self.faculty_cs_1.id))

        # 2. Coordinator sees all activities from their department (CS = 3 total)
        self.client.force_authenticate(user=self.coordinator_cs)
        res_coord = self.client.get("/api/activities/")
        self.assertEqual(res_coord.status_code, status.HTTP_200_OK)
        data_coord = res_coord.data.get("results", res_coord.data)
        self.assertEqual(len(data_coord), 3)

        # 3. Superuser sees all activities across all departments (4 total)
        self.client.force_authenticate(user=self.admin_user)
        res_admin = self.client.get("/api/activities/")
        self.assertEqual(res_admin.status_code, status.HTTP_200_OK)
        data_admin = res_admin.data.get("results", res_admin.data)
        self.assertEqual(len(data_admin), 4)

    def test_peer_benchmarking_counts_privacy_guarantee(self):
        """Peer metrics returns aggregate counts and NEVER leaks private titles or proof URLs."""
        self.client.force_authenticate(user=self.faculty_cs_1)
        res = self.client.get(f"/api/activities/metrics/department-counts/?department_id={self.dept_cs.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        records = res.data
        self.assertTrue(len(records) >= 2)

        for rec in records:
            self.assertIn("faculty_id", rec)
            self.assertIn("employee_id", rec)
            self.assertIn("counts", rec)
            self.assertIn("total_activities", rec)
            # Critical Privacy Assertion:
            self.assertNotIn("title", rec)
            self.assertNotIn("metadata", rec)
            self.assertNotIn("documents", rec)
            self.assertNotIn("direct_url", rec)

    def test_department_counts_single_query_optimization(self):
        """Single-query optimization test: Assert N+1 queries eliminated (executes in exactly 1 query)."""
        self.client.force_authenticate(user=self.faculty_cs_1)
        with self.assertNumQueries(1):
            res = self.client.get(f"/api/activities/metrics/department-counts/?department_id={self.dept_cs.id}")
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertTrue(len(res.data) >= 2)



class ExternalIntegrationAndExportAPITests(ActivityBaseTestCase):
    @patch('apps.core.services.crossref.CrossRefService.fetch_doi')
    def test_doi_enrichment_api(self, mock_fetch):
        mock_fetch.return_value = {
            "success": True,
            "data": {
                "doi": "10.1109/5.771073",
                "title": "Toward unique identifiers",
                "journal_name": "Proceedings of the IEEE",
                "publication_year": "1999"
            }
        }
        self.client.force_authenticate(user=self.faculty_cs_1)

        # Missing DOI -> 400
        res1 = self.client.post("/api/activities/auto-enrich-doi/", {"doi": ""}, format='json')
        self.assertEqual(res1.status_code, status.HTTP_400_BAD_REQUEST)

        # Valid DOI -> 200 with metadata
        res2 = self.client.post("/api/activities/auto-enrich-doi/", {"doi": "10.1109/5.771073"}, format='json')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertTrue(res2.data["success"])
        self.assertEqual(res2.data["data"]["title"], "Toward unique identifiers")

    def test_naac_criteria_3_excel_export_api(self):
        # Create an approved activity with proof
        activity = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Exportable Research Paper on Machine Learning",
            status=ActivityStatus.APPROVED,
            metadata={"journal_name": "International Journal of AI", "issn": "1234-5678", "publication_year": "2026"}
        )
        dummy_file = SimpleUploadedFile("paper.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")
        ActivityDocument.objects.create(
            activity=activity,
            document_type=DocumentType.PUBLISHED_PAPER,
            title="Reprint",
            file=dummy_file
        )

        self.client.force_authenticate(user=self.coordinator_cs)
        res = self.client.get("/api/activities/export/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertTrue(len(res.content) > 5000)

    def test_bulk_import_api_with_xlsx(self):
        import io
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Journals"
        ws.append(["S. No.", "Name of Faculty", "Emp. Id", "Department", "Title of Publictaion", "Name of Journal", "Year of Publication"])
        ws.append([1, "Dr. Sunita Rawat", "6450", "Advance Computing", "Neural Networks in Robotics", "Springer", 2026])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        uploaded = SimpleUploadedFile("bulk_test.xlsx", buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # 1. Faculty attempt -> 403 Forbidden
        self.client.force_authenticate(user=self.faculty_cs_1)
        res_fac = self.client.post("/api/activities/bulk-import/", {"file": uploaded}, format='multipart')
        self.assertEqual(res_fac.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Coordinator attempt -> 200 OK
        uploaded.seek(0)
        self.client.force_authenticate(user=self.coordinator_cs)
        res_coord = self.client.post("/api/activities/bulk-import/", {"file": uploaded}, format='multipart')
        self.assertEqual(res_coord.status_code, status.HTTP_200_OK)
        self.assertTrue(res_coord.data["success"])
        self.assertEqual(res_coord.data["created"], 1)

    def test_admin_bulk_import_workflow(self):
        import io
        import openpyxl
        from django.test import Client
        c = Client()
        c.force_login(self.coordinator_cs)

        # GET admin import page
        res_get = c.get("/admin/activities/activity/bulk-import/")
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, "Bulk Ingestion Console")

        # POST file
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Patents"
        ws.append(["S. No.", "Name of Faculty", "Emp. Id", "Department", "Title of Patent", "Patent Application Number"])
        ws.append([1, "Dr. Priya Verma", "FAC002", "CSE", "IoT Based Smart Grid Node", "202611001234"])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        uploaded = SimpleUploadedFile("admin_test.xlsx", buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        res_post = c.post("/admin/activities/activity/bulk-import/", {"import_file": uploaded})
        self.assertEqual(res_post.status_code, 302)
        self.assertIn("/admin/activities/activity/", res_post.url)

    def test_faculty_can_use_django_admin_directly(self):
        """Verifies faculty can log into Django Admin, see only their own data, and submit activities."""
        from django.test import Client
        self.faculty_cs_1.is_staff = True
        self.faculty_cs_1.save()

        c = Client()
        c.force_login(self.faculty_cs_1)

        # 1. Faculty visits Admin dashboard
        res_dash = c.get("/admin/")
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, "Poornima University")
        # Sidebar should hide RBAC and Bulk Import for faculty
        self.assertNotContains(res_dash, "Bulk Import (Excel / ZIP)")
        self.assertNotContains(res_dash, "Roles & Permissions")

        # 2. Faculty visits Activity Changelist
        res_list = c.get("/admin/activities/activity/")
        self.assertEqual(res_list.status_code, 200)

        # 3. Faculty visits Add Activity form
        res_add = c.get("/admin/activities/activity/add/")
        self.assertEqual(res_add.status_code, 200)

        # 4. Faculty attempts batch approval -> must be blocked
        act = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Faculty Self-Approval Attempt",
            status=ActivityStatus.SUBMITTED
        )
        res_batch = c.post("/admin/activities/activity/", {
            "action": "approve_selected_activities",
            "_selected_action": [str(act.id)]
        }, follow=True)
        self.assertEqual(res_batch.status_code, 200)
        act.refresh_from_db()
        # Must still be submitted, NOT approved
        self.assertEqual(act.status, ActivityStatus.SUBMITTED)


class PolymorphicFormAndDynamicAttributesTests(ActivityBaseTestCase):
    def test_admin_form_unpacks_metadata_to_key_value_rows(self):
        from apps.activities.forms import ActivityAdminForm
        from django import forms

        act = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Quantum Cryptography Protocols",
            status=ActivityStatus.SUBMITTED,
            metadata={
                "name_of_journal": "IEEE Transactions on Information Forensics",
                "isbn_issn_(if_applicable)": "1556-6013",
                "volume_no": "18",
                "Grant Amount": "INR 12,00,000",
                "Industry Partner": "Tata Consultancy Services"
            }
        )

        form = ActivityAdminForm(instance=act)
        # Check initial contains raw metadata dictionary
        self.assertEqual(form.initial["metadata_kv_editor"], act.metadata)

        # Render form to HTML and verify every key and value is rendered as an input
        html_rendered = str(form["metadata_kv_editor"])
        self.assertIn('name="meta_keys"', html_rendered)
        self.assertIn('name="meta_values"', html_rendered)
        self.assertIn('value="name_of_journal"', html_rendered)
        self.assertIn('value="IEEE Transactions on Information Forensics"', html_rendered)
        self.assertIn('value="Grant Amount"', html_rendered)
        self.assertIn('value="INR 12,00,000"', html_rendered)

        # Raw JSON metadata field is hidden
        self.assertIsInstance(form.fields["metadata"].widget, forms.HiddenInput)

    def test_admin_form_packs_key_value_inputs_into_metadata(self):
        from apps.activities.forms import ActivityAdminForm
        from django.http import QueryDict

        qd = QueryDict('', mutable=True)
        qd.update({
            "title": "Smart City IoT Sensor Grid",
            "faculty": str(self.faculty_cs_1.id),
            "academic_session": str(self.session.id),
            "activity_type": ActivityType.PATENT,
            "status": ActivityStatus.SUBMITTED,
        })
        qd.setlist("meta_keys", ["application_number", "patent_status", "Grant Amount", "TRL Level"])
        qd.setlist("meta_values", ["202611009876", "Published", "INR 7,50,000", "TRL 6"])

        form = ActivityAdminForm(data=qd)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()

        # Metadata should contain all keys and values submitted
        self.assertEqual(saved.metadata["application_number"], "202611009876")
        self.assertEqual(saved.metadata["patent_status"], "Published")
        self.assertEqual(saved.metadata["Grant Amount"], "INR 7,50,000")
        self.assertEqual(saved.metadata["TRL Level"], "TRL 6")

    def test_admin_add_and_change_pages_render_key_value_editor(self):
        from django.test import Client
        c = Client()
        c.force_login(self.admin_user)

        # 1. Add page
        res_add = c.get("/admin/activities/activity/add/")
        self.assertEqual(res_add.status_code, 200)
        self.assertContains(res_add, "Attributes &amp; Custom Fields")
        self.assertContains(res_add, "Key (Field Name)")
        self.assertContains(res_add, "Value (Data)")
        self.assertContains(res_add, "+ Add Field")
        self.assertContains(res_add, "+ Load Template Keys")

        # 2. Change page with existing metadata
        act = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Existing Achievement with Metadata",
            status=ActivityStatus.SUBMITTED,
            metadata={"Custom Key": "Custom Value 123"}
        )
        res_change = c.get(f"/admin/activities/activity/{act.id}/change/")
        self.assertEqual(res_change.status_code, 200)
        self.assertContains(res_change, "Custom Key")
        self.assertContains(res_change, "Custom Value 123")


class DynamicModuleRBACTests(ActivityBaseTestCase):
    def test_faculty_with_is_staff_cannot_approve_activities(self):
        """Staff flag must NOT bypass module RBAC: faculty cannot approve achievements."""
        self.faculty_cs_1.is_staff = True
        self.faculty_cs_1.save()

        act = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Paper for Self-Approval Attempt",
            status=ActivityStatus.SUBMITTED
        )
        dummy_pdf = SimpleUploadedFile("proof.pdf", b"%PDF-1.4 test proof", content_type="application/pdf")
        ActivityDocument.objects.create(
            activity=act,
            document_type=DocumentType.PUBLISHED_PAPER,
            title="Proof Attachment",
            file=dummy_pdf
        )

        self.client.force_authenticate(user=self.faculty_cs_1)
        res = self.client.post(f"/api/activities/{act.id}/approve/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        act.refresh_from_db()
        self.assertEqual(act.status, ActivityStatus.SUBMITTED)

    def test_coordinator_cannot_self_approve_own_activity(self):
        """Coordinators have approval rights for department, but strictly CANNOT approve their own activity."""
        coord_act = Activity.objects.create(
            faculty=self.coordinator_cs,
            academic_session=self.session,
            activity_type=ActivityType.PATENT,
            title="Coordinator Own Patent",
            status=ActivityStatus.SUBMITTED
        )
        dummy_pdf = SimpleUploadedFile("patent_proof.pdf", b"%PDF-1.4 patent proof", content_type="application/pdf")
        ActivityDocument.objects.create(
            activity=coord_act,
            document_type=DocumentType.PATENT_GRANT_CERTIFICATE,
            title="Patent Certificate",
            file=dummy_pdf
        )

        self.client.force_authenticate(user=self.coordinator_cs)
        res = self.client.post(f"/api/activities/{coord_act.id}/approve/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        coord_act.refresh_from_db()
        self.assertEqual(coord_act.status, ActivityStatus.SUBMITTED)

    def test_faculty_cannot_spoof_faculty_field_on_create(self):
        """Faculty member cannot create an activity on behalf of another faculty member."""
        self.faculty_cs_1.is_staff = True
        self.faculty_cs_1.save()

        self.client.force_authenticate(user=self.faculty_cs_1)
        payload = {
            "faculty": str(self.faculty_cs_2.id),
            "academic_session": str(self.session.id),
            "activity_type": ActivityType.JOURNAL_PUBLICATION,
            "title": "Attempted Spoofed Publication",
            "status": ActivityStatus.DRAFT,
            "metadata": {"journal_name": "International Journal of Testing"}
        }
        res = self.client.post("/api/activities/", payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        # Even though faculty_cs_2 ID was provided, backend forces faculty to request.user
        created_act = Activity.objects.get(id=res.data["id"])
        self.assertEqual(created_act.faculty, self.faculty_cs_1)


class Phase2ExportAndImportTests(ActivityBaseTestCase):
    def setUp(self):
        super().setUp()
        self.mod_activities, _ = Module.objects.get_or_create(code="activities", defaults={"name": "Activities"})
        self.mod_reports, _ = Module.objects.get_or_create(code="reports", defaults={"name": "Reports"})

        # Faculty has view/create/edit/export on activities and reports
        RolePermission.objects.update_or_create(
            role=self.role_faculty,
            module=self.mod_activities,
            defaults={"can_view": True, "can_create": True, "can_edit": True, "can_approve": False, "can_export": True}
        )
        RolePermission.objects.update_or_create(
            role=self.role_faculty,
            module=self.mod_reports,
            defaults={"can_view": True, "can_export": True}
        )

        # Coordinator has all rights on activities
        RolePermission.objects.update_or_create(
            role=self.role_coord,
            module=self.mod_activities,
            defaults={"can_view": True, "can_create": True, "can_edit": True, "can_approve": True, "can_export": True}
        )

    def test_faculty_can_export_own_activities(self):
        """Faculty with view permission can export their own approved achievements."""
        act = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Faculty 1 Approved Paper",
            status=ActivityStatus.APPROVED
        )
        self.client.force_authenticate(user=self.faculty_cs_1)
        res = self.client.get("/api/activities/export/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_user_without_view_permission_cannot_export(self):
        """A user without view permission on activities or reports cannot export."""
        RolePermission.objects.filter(role=self.role_faculty, module=self.mod_activities).update(can_view=False)
        RolePermission.objects.filter(role=self.role_faculty, module=self.mod_reports).update(can_view=False)

        self.client.force_authenticate(user=self.faculty_cs_1)
        res = self.client.get("/api/activities/export/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_faculty_cannot_perform_bulk_import(self):
        """Faculty without activities approve permissions cannot perform bulk imports."""
        self.client.force_authenticate(user=self.faculty_cs_1)
        dummy_file = SimpleUploadedFile("test.xlsx", b"dummy content", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        res = self.client.post("/api/activities/bulk-import/", {"file": dummy_file}, format="multipart")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_coordinator_can_access_bulk_import(self):
        """Coordinator with activities approve permissions is permitted to perform bulk imports."""
        self.client.force_authenticate(user=self.coordinator_cs)
        # Even with invalid format, it passes authorization check (returns 400 bad request, NOT 403 forbidden)
        dummy_file = SimpleUploadedFile("test.txt", b"invalid format", content_type="text/plain")
        res = self.client.post("/api/activities/bulk-import/", {"file": dummy_file}, format="multipart")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Unsupported file format", res.data["error"])


class Phase5RecordLockingAndBatchStatusTests(ActivityBaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Create sample activities
        self.act1_cs = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="High Performance Computing Research",
            status=ActivityStatus.SUBMITTED,
            metadata={"journal_name": "IEEE TPDS"}
        )
        # Attach proof to act1
        ActivityDocument.objects.create(
            activity=self.act1_cs,
            file=SimpleUploadedFile("proof1.pdf", b"%PDF-1.4 sample", content_type="application/pdf"),
            document_type=DocumentType.PUBLISHED_PAPER
        )

        self.act2_cs = Activity.objects.create(
            faculty=self.faculty_cs_2,
            academic_session=self.session,
            activity_type=ActivityType.CONFERENCE_PUBLICATION,
            title="Distributed Systems at Scale",
            status=ActivityStatus.SUBMITTED,
            metadata={"conference_name": "ACM SIGCOMM"}
        )
        # Attach proof to act2
        ActivityDocument.objects.create(
            activity=self.act2_cs,
            file=SimpleUploadedFile("proof2.pdf", b"%PDF-1.4 sample", content_type="application/pdf"),
            document_type=DocumentType.PUBLISHED_PAPER
        )

        # Activity belonging to coordinator themselves
        self.act_coord = Activity.objects.create(
            faculty=self.coordinator_cs,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Coordinator Own Research Paper",
            status=ActivityStatus.SUBMITTED,
            metadata={"journal_name": "ACM Computing Surveys"}
        )
        ActivityDocument.objects.create(
            activity=self.act_coord,
            file=SimpleUploadedFile("coord_proof.pdf", b"%PDF-1.4 sample", content_type="application/pdf"),
            document_type=DocumentType.PUBLISHED_PAPER
        )

        # Activity belonging to another department (AIDS)
        self.act_ai = Activity.objects.create(
            faculty=self.faculty_ai,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Neural Architecture Search",
            status=ActivityStatus.SUBMITTED,
            metadata={"journal_name": "NeurIPS"}
        )
        ActivityDocument.objects.create(
            activity=self.act_ai,
            file=SimpleUploadedFile("ai_proof.pdf", b"%PDF-1.4 sample", content_type="application/pdf"),
            document_type=DocumentType.PUBLISHED_PAPER
        )

    def test_approved_activity_immutability_rest_api(self):
        """Approved activity cannot be modified or deleted via REST API by non-superusers."""
        # Approve act1 first
        self.act1_cs.status = ActivityStatus.APPROVED
        self.act1_cs.save()

        # Faculty tries to PATCH title
        self.client.force_authenticate(user=self.faculty_cs_1)
        res_patch = self.client.patch(
            f"/api/activities/{self.act1_cs.id}/",
            {"title": "Tampered Title Attempt"},
            format="json"
        )
        self.assertEqual(res_patch.status_code, status.HTTP_403_FORBIDDEN)
        self.act1_cs.refresh_from_db()
        self.assertEqual(self.act1_cs.title, "High Performance Computing Research")

        # Faculty tries to DELETE
        res_del = self.client.delete(f"/api/activities/{self.act1_cs.id}/")
        self.assertEqual(res_del.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Activity.objects.filter(id=self.act1_cs.id).exists())

    def test_faculty_can_delete_own_draft_activity(self):
        """Faculty can delete their own draft activity."""
        draft_act = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Draft Publication for Deletion",
            status=ActivityStatus.DRAFT,
            metadata={"journal_name": "Test Journal"}
        )
        self.client.force_authenticate(user=self.faculty_cs_1)
        res_del = self.client.delete(f"/api/activities/{draft_act.id}/")
        self.assertEqual(res_del.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Activity.objects.filter(id=draft_act.id).exists())

    def test_faculty_cannot_delete_other_faculty_draft_activity(self):
        """Faculty cannot delete another faculty's draft activity."""
        draft_act = Activity.objects.create(
            faculty=self.faculty_cs_2,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Other Faculty Draft Publication",
            status=ActivityStatus.DRAFT,
            metadata={"journal_name": "Test Journal"}
        )
        self.client.force_authenticate(user=self.faculty_cs_1)
        res_del = self.client.delete(f"/api/activities/{draft_act.id}/")
        self.assertIn(res_del.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))
        self.assertTrue(Activity.objects.filter(id=draft_act.id).exists())

    def test_faculty_can_delete_own_document_on_draft_activity(self):
        """Faculty can delete their own document on an unapproved activity."""
        doc = ActivityDocument.objects.create(
            activity=self.act1_cs,
            file=SimpleUploadedFile("delete_me.pdf", b"%PDF-1.4 delete test", content_type="application/pdf"),
            document_type=DocumentType.PUBLISHED_PAPER
        )
        self.act1_cs.status = ActivityStatus.DRAFT
        self.act1_cs.save()

        self.client.force_authenticate(user=self.faculty_cs_1)
        res_del = self.client.delete(f"/api/documents/{doc.id}/")
        self.assertEqual(res_del.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ActivityDocument.objects.filter(id=doc.id).exists())

    def test_superuser_can_modify_approved_activity(self):
        """Superusers can modify approved activities when necessary."""
        self.act1_cs.status = ActivityStatus.APPROVED
        self.act1_cs.save()

        self.client.force_authenticate(user=self.admin_user)
        res_patch = self.client.patch(
            f"/api/activities/{self.act1_cs.id}/",
            {"title": "Admin Verified Update"},
            format="json"
        )
        self.assertEqual(res_patch.status_code, status.HTTP_200_OK)
        self.act1_cs.refresh_from_db()
        self.assertEqual(self.act1_cs.title, "Admin Verified Update")

    def test_unauthorized_status_transition_blocked(self):
        """Regular faculty cannot transition status directly to approved via PUT/PATCH."""
        self.client.force_authenticate(user=self.faculty_cs_1)
        res = self.client.patch(
            f"/api/activities/{self.act1_cs.id}/",
            {"status": ActivityStatus.APPROVED},
            format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", res.data)

    def test_activity_clean_immutability(self):
        """Model clean() raises ValidationError if core details of an approved activity are modified."""
        from django.core.exceptions import ValidationError

        self.act1_cs.status = ActivityStatus.APPROVED
        self.act1_cs.save()

        self.act1_cs.title = "Direct Model Modification Attempt"
        with self.assertRaises(ValidationError):
            self.act1_cs.clean()

    def test_batch_status_update_unauthorized(self):
        """Users without activities.approve permission cannot access batch-status-update."""
        self.client.force_authenticate(user=self.faculty_cs_1)
        payload = {
            "activity_ids": [str(self.act1_cs.id), str(self.act2_cs.id)],
            "status": ActivityStatus.APPROVED
        }
        res = self.client.post("/api/activities/batch-status-update/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_batch_status_update_approve_success(self):
        """Coordinator can approve multiple department activities atomically."""
        self.client.force_authenticate(user=self.coordinator_cs)
        payload = {
            "activity_ids": [str(self.act1_cs.id), str(self.act2_cs.id)],
            "status": ActivityStatus.APPROVED
        }
        res = self.client.post("/api/activities/batch-status-update/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        self.assertEqual(res.data["updated_count"], 2)

        self.act1_cs.refresh_from_db()
        self.act2_cs.refresh_from_db()
        self.assertEqual(self.act1_cs.status, ActivityStatus.APPROVED)
        self.assertEqual(self.act2_cs.status, ActivityStatus.APPROVED)
        self.assertEqual(self.act1_cs.verified_by, self.coordinator_cs)
        self.assertIsNotNone(self.act1_cs.verified_at)

    def test_batch_status_update_self_approval_blocked(self):
        """Including coordinator's own activity in batch approval is blocked and rolls back."""
        self.client.force_authenticate(user=self.coordinator_cs)
        payload = {
            "activity_ids": [str(self.act1_cs.id), str(self.act_coord.id)],
            "status": ActivityStatus.APPROVED
        }
        res = self.client.post("/api/activities/batch-status-update/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Self-approval is strictly prohibited", str(res.data))

        # Verify rollback: act1_cs must NOT have been approved
        self.act1_cs.refresh_from_db()
        self.assertEqual(self.act1_cs.status, ActivityStatus.SUBMITTED)

    def test_batch_status_update_missing_proof_blocked(self):
        """Batch approval fails and rolls back if any activity lacks proof attachments."""
        # Create an activity with NO documents
        act_no_doc = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.PATENT,
            title="Unproven Patent Filing",
            status=ActivityStatus.SUBMITTED,
            metadata={"patent_or_application_number": "IN2026110022"}
        )

        self.client.force_authenticate(user=self.coordinator_cs)
        payload = {
            "activity_ids": [str(self.act1_cs.id), str(act_no_doc.id)],
            "status": ActivityStatus.APPROVED
        }
        res = self.client.post("/api/activities/batch-status-update/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Missing mandatory proof document attachment", str(res.data))

        self.act1_cs.refresh_from_db()
        self.assertEqual(self.act1_cs.status, ActivityStatus.SUBMITTED)

    def test_batch_status_update_department_jurisdiction_blocked(self):
        """Coordinator cannot change status of activities outside their department."""
        self.client.force_authenticate(user=self.coordinator_cs)
        payload = {
            "activity_ids": [str(self.act1_cs.id), str(self.act_ai.id)],
            "status": ActivityStatus.APPROVED
        }
        res = self.client.post("/api/activities/batch-status-update/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("outside your jurisdiction", str(res.data))

        self.act1_cs.refresh_from_db()
        self.assertEqual(self.act1_cs.status, ActivityStatus.SUBMITTED)

    def test_batch_status_update_rejection(self):
        """Batch rejection atomically updates activities with mandatory comment."""
        self.client.force_authenticate(user=self.coordinator_cs)
        payload = {
            "activity_ids": [str(self.act1_cs.id), str(self.act2_cs.id)],
            "status": ActivityStatus.REJECTED,
            "rejection_reason": "Incomplete indexing proof screenshot."
        }
        res = self.client.post("/api/activities/batch-status-update/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.act1_cs.refresh_from_db()
        self.assertEqual(self.act1_cs.status, ActivityStatus.REJECTED)
        self.assertEqual(self.act1_cs.rejection_reason, "Incomplete indexing proof screenshot.")
        self.assertEqual(self.act1_cs.verified_by, self.coordinator_cs)

    def test_batch_status_update_rejection_requires_reason(self):
        """Batch rejection without a reason returns 400 Bad Request."""
        self.client.force_authenticate(user=self.coordinator_cs)
        payload = {
            "activity_ids": [str(self.act1_cs.id)],
            "status": ActivityStatus.REJECTED,
            "rejection_reason": "   "
        }
        res = self.client.post("/api/activities/batch-status-update/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rejection_reason", res.data["error"])

    def test_batch_status_update_reset_to_draft(self):
        """Batch status update can reset activities back to Draft status."""
        self.client.force_authenticate(user=self.coordinator_cs)
        payload = {
            "activity_ids": [str(self.act1_cs.id), str(self.act2_cs.id)],
            "status": ActivityStatus.DRAFT
        }
        res = self.client.post("/api/activities/batch-status-update/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.act1_cs.refresh_from_db()
        self.act2_cs.refresh_from_db()
        self.assertEqual(self.act1_cs.status, ActivityStatus.DRAFT)
        self.assertIsNone(self.act1_cs.verified_by)

    def test_admin_batch_actions_and_permissions(self):
        """Tests Unfold Django Admin batch actions and approved record immutability."""
        from django.contrib.admin.sites import AdminSite
        from apps.activities.admin import ActivityAdmin
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage

        site = AdminSite()
        admin_obj = ActivityAdmin(Activity, site)
        rf = RequestFactory()

        # 1. Non-superuser has_delete_permission and get_readonly_fields on approved activity
        req_coord = rf.post('/admin/activities/activity/')
        req_coord.user = self.coordinator_cs
        self.act1_cs.status = ActivityStatus.APPROVED
        self.act1_cs.save()

        # Delete permission must be False
        self.assertFalse(admin_obj.has_delete_permission(req_coord, obj=self.act1_cs))

        # Core fields must be in readonly_fields
        ro = admin_obj.get_readonly_fields(req_coord, obj=self.act1_cs)
        self.assertIn('title', ro)
        self.assertIn('status', ro)
        self.assertIn('metadata_kv_editor', ro)

        # Superuser delete permission must be True
        req_admin = rf.post('/admin/activities/activity/')
        req_admin.user = self.admin_user
        self.assertTrue(admin_obj.has_delete_permission(req_admin, obj=self.act1_cs))

        # 2. Batch approval via admin
        self.act1_cs.status = ActivityStatus.SUBMITTED
        self.act1_cs.save()
        self.act2_cs.status = ActivityStatus.SUBMITTED
        self.act2_cs.save()

        setattr(req_coord, 'session', {})
        setattr(req_coord, '_messages', FallbackStorage(req_coord))

        qs = Activity.objects.filter(id__in=[self.act1_cs.id, self.act2_cs.id])
        admin_obj.approve_selected_activities(req_coord, qs)

        self.act1_cs.refresh_from_db()
        self.act2_cs.refresh_from_db()
        self.assertEqual(self.act1_cs.status, ActivityStatus.APPROVED)
        self.assertEqual(self.act2_cs.status, ActivityStatus.APPROVED)
        self.assertEqual(self.act1_cs.verified_by, self.coordinator_cs)

        # 3. Batch rejection via admin
        admin_obj.reject_selected_activities(req_coord, qs)
        self.act1_cs.refresh_from_db()
        self.assertEqual(self.act1_cs.status, ActivityStatus.REJECTED)

        # 4. Batch draft via admin
        admin_obj.mark_draft(req_coord, qs)
        self.act1_cs.refresh_from_db()
        self.assertEqual(self.act1_cs.status, ActivityStatus.DRAFT)
        self.assertIsNone(self.act1_cs.verified_by)


class Phase8FrontendAPIAndPaginationTests(ActivityBaseTestCase):
    """Automated tests for Global Cursor Pagination, NAAC Export Hardening, and Frontend Supporting APIs."""

    def test_cursor_pagination_on_activities_endpoint(self):
        c = Client()
        c.force_login(self.admin_user)

        res = c.get('/api/activities/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('next', data)
        self.assertIn('previous', data)
        self.assertIn('results', data)
        self.assertIsNone(data['previous'])
        self.assertIsInstance(data['results'], list)

    def test_cursor_pagination_custom_page_size(self):
        # Create activities for pagination test
        for i in range(3):
            Activity.objects.create(
                faculty=self.faculty_cs_1,
                academic_session=self.session,
                activity_type=ActivityType.JOURNAL_PUBLICATION,
                title=f"Paper {i}",
                status=ActivityStatus.APPROVED
            )

        c = Client()
        c.force_login(self.admin_user)

        res = c.get('/api/activities/?page_size=1')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data['results']), 1)
        self.assertIsNotNone(data['next'])

        # Traverse to next page using cursor URL
        res_next = c.get(data['next'])
        self.assertEqual(res_next.status_code, 200)
        data_next = res_next.json()
        self.assertEqual(len(data_next['results']), 1)
        self.assertIsNotNone(data_next['previous'])

    def test_naac_export_with_status_query_param(self):
        import openpyxl, io
        # Create a submitted participation activity
        Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.FACULTY_PARTICIPATION,
            title="FDP on Cloud Computing",
            status=ActivityStatus.SUBMITTED,
            metadata={
                "title_of_the_professional_development_program": "FDP on Cloud Computing",
                "type_of_program(fdp/seminar/workshop)": "FDP",
                "dates_(from-to)(dd-mm-yyyy)": "01-08-2026 to 05-08-2026"
            }
        )

        c = Client()
        c.force_login(self.admin_user)

        # 1. Default (approved only)
        res_approved = c.get('/api/activities/export/')
        self.assertEqual(res_approved.status_code, 200)
        wb_app = openpyxl.load_workbook(io.BytesIO(res_approved.content))
        self.assertIn('NAAC 3.4.3 (Journals)', wb_app.sheetnames)

        # 2. ?status=all (includes submitted records)
        res_all = c.get('/api/activities/export/?status=all')
        self.assertEqual(res_all.status_code, 200)
        wb_all = openpyxl.load_workbook(io.BytesIO(res_all.content))
        ws_part = wb_all['NAAC 3.4.6 (Participation)']
        self.assertGreater(ws_part.max_row, 1)

        # 3. ?status=submitted
        res_sub = c.get('/api/activities/export/?status=submitted')
        self.assertEqual(res_sub.status_code, 200)

    def test_naac_export_metadata_alias_resolution(self):
        import openpyxl, io
        # Create an activity with raw Excel column header slugs
        act = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Quantum Machine Learning for Healthcare",
            status=ActivityStatus.SUBMITTED,
            metadata={
                "name_of_journal": "IEEE Trans Quantum Computing",
                "isbn_issn_(if_applicable)": "9999-8888",
                "indexing(if_any)_eg_scopus,_sci,_ugc_car": "SCI / Scopus",
                "date_of_publication": "2026-05-15 00:00:00",
                "doi": "https://doi.org/10.1109/TQC.2026.12345"
            }
        )

        c = Client()
        c.force_login(self.admin_user)
        res = c.get('/api/activities/export/?status=all')
        self.assertEqual(res.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        ws = wb['NAAC 3.4.3 (Journals)']

        # Verify the aliased metadata was resolved into the sheet cells
        found = False
        for r in range(2, ws.max_row + 1):
            if ws.cell(row=r, column=6).value == "Quantum Machine Learning for Healthcare":
                found = True
                self.assertEqual(ws.cell(row=r, column=7).value, "IEEE Trans Quantum Computing")
                self.assertEqual(ws.cell(row=r, column=8).value, "2026")
                self.assertEqual(ws.cell(row=r, column=9).value, "9999-8888")
                self.assertEqual(ws.cell(row=r, column=10).value, "SCI / Scopus")
                self.assertEqual(ws.cell(row=r, column=11).value, "https://doi.org/10.1109/TQC.2026.12345")
                break
        self.assertTrue(found, "Newly created aliased activity was not found in exported sheet")

    def test_activity_metadata_view(self):
        c = Client()
        c.force_login(self.faculty_cs_1)

        res = c.get('/api/activities/meta/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('activity_types', data)
        self.assertIn('activity_statuses', data)
        self.assertIn('document_types', data)
        self.assertIn('metadata_templates', data)
        self.assertIn(ActivityType.JOURNAL_PUBLICATION, data['metadata_templates'])

    def test_bulk_import_api_permissions_and_validation(self):
        c = Client()

        # 1. Faculty without approve perm -> 403 Forbidden
        c.force_login(self.faculty_cs_1)
        res_fac = c.post('/api/activities/bulk-import/')
        self.assertEqual(res_fac.status_code, 403)

        # 2. Coordinator with approve perm -> missing file -> 400 Bad Request
        c.force_login(self.coordinator_cs)
        res_coord = c.post('/api/activities/bulk-import/')
        self.assertEqual(res_coord.status_code, 400)
        self.assertIn("error", res_coord.json())

        # 3. Coordinator with unsupported file format -> 400 Bad Request
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad_file = SimpleUploadedFile("test.txt", b"plain text content", content_type="text/plain")
        res_bad = c.post('/api/activities/bulk-import/', {'file': bad_file}, format='multipart')
        self.assertEqual(res_bad.status_code, 400)

    def test_accounts_supporting_viewsets(self):
        c = Client()
        c.force_login(self.faculty_cs_1)

        # 1. Modules list
        res_mod = c.get('/api/accounts/modules/')
        self.assertEqual(res_mod.status_code, 200)
        self.assertIn('results', res_mod.json())

        # 2. Roles list
        res_roles = c.get('/api/accounts/roles/')
        self.assertEqual(res_roles.status_code, 200)
        self.assertIn('results', res_roles.json())

        # 3. Permissions list
        res_perm = c.get('/api/accounts/permissions/')
        self.assertEqual(res_perm.status_code, 200)
        self.assertIn('results', res_perm.json())

        # 4. Users list with filter by department
        res_users = c.get(f'/api/accounts/users/?department={self.dept_cs.id}')
        self.assertEqual(res_users.status_code, 200)
        self.assertIn('results', res_users.json())
        results = res_users.json()['results']
        self.assertTrue(len(results) > 0)
        for u in results:
            self.assertEqual(u['department'], str(self.dept_cs.id))


class Phase8ExportQueryParamsAndAdminConsoleTests(ActivityBaseTestCase):
    """Automated tests for rich export query parameters (API & Admin) and Unfold Admin Export Console."""

    def setUp(self):
        super().setUp()
        import openpyxl, io
        # Create test activities with varied statuses and proofs
        self.act1 = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Deep Learning with Proof",
            status=ActivityStatus.APPROVED,
            metadata={"name_of_journal": "IEEE Transactions on AI"}
        )
        self.doc1 = ActivityDocument.objects.create(
            activity=self.act1,
            title="Proof 1",
            file="proofs/test_proof.pdf",
            is_verified=True
        )

        self.act2 = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.PATENT,
            title="Quantum Blockchain Patent",
            status=ActivityStatus.SUBMITTED,
            metadata={"patent_number": "IN2026/001", "country": "India"}
        )

        self.act3 = Activity.objects.create(
            faculty=self.faculty_ai,
            academic_session=self.session,
            activity_type=ActivityType.CONFERENCE_PUBLICATION,
            title="Thermodynamics in Robotics",
            status=ActivityStatus.DRAFT,
            metadata={"conference_name": "ICRA 2026"}
        )

    def test_api_export_with_verified_and_proof_filters(self):
        import openpyxl, io
        c = Client()
        c.force_login(self.admin_user)

        # 1. verified=true (act1 is approved and has verified doc)
        res_v = c.get('/api/activities/export/?status=all&verified=true')
        self.assertEqual(res_v.status_code, 200)
        wb_v = openpyxl.load_workbook(io.BytesIO(res_v.content))
        ws_j = wb_v['NAAC 3.4.3 (Journals)']
        self.assertGreater(ws_j.max_row, 1)

        # 2. has_proof=true
        res_p = c.get('/api/activities/export/?status=all&has_proof=true')
        self.assertEqual(res_p.status_code, 200)
        wb_p = openpyxl.load_workbook(io.BytesIO(res_p.content))
        ws_pj = wb_p['NAAC 3.4.3 (Journals)']
        self.assertGreater(ws_pj.max_row, 1)

        # 3. has_proof=false (act2 has no proof)
        res_np = c.get('/api/activities/export/?status=all&has_proof=false')
        self.assertEqual(res_np.status_code, 200)
        wb_np = openpyxl.load_workbook(io.BytesIO(res_np.content))
        ws_pat = wb_np['NAAC 3.4.5 (Patents)']
        self.assertGreater(ws_pat.max_row, 1)

    def test_api_export_with_activity_type_filter(self):
        import openpyxl, io
        c = Client()
        c.force_login(self.admin_user)

        # Filter by single type: patent
        res = c.get('/api/activities/export/?status=all&activity_type=patent')
        self.assertEqual(res.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        self.assertEqual(wb.sheetnames, ['NAAC 3.4.5 (Patents)'])
        ws = wb['NAAC 3.4.5 (Patents)']
        self.assertGreater(ws.max_row, 1)

        # Filter by multiple comma-separated types: journal_publication,patent
        res_multi = c.get('/api/activities/export/?status=all&activity_type=journal_publication,patent')
        self.assertEqual(res_multi.status_code, 200)
        wb_multi = openpyxl.load_workbook(io.BytesIO(res_multi.content))
        self.assertIn('NAAC 3.4.3 (Journals)', wb_multi.sheetnames)
        self.assertIn('NAAC 3.4.5 (Patents)', wb_multi.sheetnames)
        self.assertNotIn('NAAC 3.4.4 (Conferences)', wb_multi.sheetnames)

    def test_api_export_with_search_and_selected_ids(self):
        import openpyxl, io
        c = Client()
        c.force_login(self.admin_user)

        # Search by title keyword
        res_s = c.get('/api/activities/export/?status=all&search=Quantum')
        self.assertEqual(res_s.status_code, 200)
        wb_s = openpyxl.load_workbook(io.BytesIO(res_s.content))
        ws_pat = wb_s['NAAC 3.4.5 (Patents)']
        self.assertGreater(ws_pat.max_row, 1)
        # Journals sheet should be empty of data rows (only header)
        ws_j = wb_s['NAAC 3.4.3 (Journals)']
        self.assertEqual(ws_j.max_row, 1)

        # Filter by exact ID
        res_id = c.get(f'/api/activities/export/?status=all&ids={self.act1.id}')
        self.assertEqual(res_id.status_code, 200)
        wb_id = openpyxl.load_workbook(io.BytesIO(res_id.content))
        ws_j_id = wb_id['NAAC 3.4.3 (Journals)']
        self.assertEqual(ws_j_id.max_row, 2)

    def test_admin_export_console_get_and_post(self):
        import openpyxl, io
        c = Client()
        c.force_login(self.admin_user)

        # GET render
        res_get = c.get('/admin/activities/activity/export/')
        self.assertEqual(res_get.status_code, 200)
        self.assertIn("NAAC AQAR Criteria 3 Export Console", res_get.content.decode())

        # POST download
        res_post = c.post('/admin/activities/activity/export/', {
            'academic_session': 'all',
            'department': 'all',
            'status': ['approved', 'submitted'],
            'verified': 'all',
            'has_proof': 'all',
            'activity_type': ['journal_publication'],
        })
        self.assertEqual(res_post.status_code, 200)
        self.assertIn('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', res_post['Content-Type'])
        self.assertIn('attachment', res_post['Content-Disposition'])
        wb_post = openpyxl.load_workbook(io.BytesIO(res_post.content))
        self.assertEqual(wb_post.sheetnames, ['NAAC 3.4.3 (Journals)'])

    def test_admin_export_selected_activities_action(self):
        from apps.activities.admin import ActivityAdmin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        site = AdminSite()
        admin_obj = ActivityAdmin(Activity, site)
        rf = RequestFactory()
        req = rf.post('/admin/activities/activity/')
        req.user = self.admin_user

        qs = Activity.objects.filter(id__in=[self.act1.id, self.act2.id])
        res = admin_obj.export_selected_activities_action(req, qs)
        self.assertEqual(res.status_code, 200)
        self.assertIn('attachment', res['Content-Disposition'])


class UserSummaryAndPermissionEnhancementTests(ActivityBaseTestCase):
    def setUp(self):
        super().setUp()
        self.act_cs1 = Activity.objects.create(
            faculty=self.faculty_cs_1,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="CS1 Paper",
            status=ActivityStatus.APPROVED,
            metadata={"name_of_journal": "IEEE"}
        )
        self.act_cs2 = Activity.objects.create(
            faculty=self.faculty_cs_2,
            academic_session=self.session,
            activity_type=ActivityType.CONFERENCE_PUBLICATION,
            title="CS2 Conference",
            status=ActivityStatus.SUBMITTED,
            metadata={"conference_name": "ACM"}
        )
        self.act_ai = Activity.objects.create(
            faculty=self.faculty_ai,
            academic_session=self.session,
            activity_type=ActivityType.PATENT,
            title="AI Patent",
            status=ActivityStatus.APPROVED,
            metadata={"patent_number": "PAT123"}
        )

    def test_default_group_and_role_auto_assignment(self):
        """Users created without an explicit role or group are automatically assigned default faculty role and group."""
        from django.contrib.auth.models import Group
        new_user = User.objects.create_user(
            username="new_regular_faculty",
            email="regular@poornima.org",
            password="password123",
            first_name="Regular",
            last_name="Member"
        )
        self.assertIsNotNone(new_user.role)
        self.assertEqual(new_user.role.code, "faculty")
        self.assertTrue(new_user.groups.filter(name="Faculty").exists())

    def test_user_summary_endpoint_permissions_and_counts(self):
        """User summary endpoint returns achievement counts and calculated can_view_details based on viewer role."""
        # Authenticate as regular faculty
        self.client.force_authenticate(user=self.faculty_cs_1)
        res = self.client.get('/api/activities/user-summary/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data

        # Find self and another faculty
        self_row = next((u for u in data if u['username'] == self.faculty_cs_1.username), None)
        other_row = next((u for u in data if u['username'] == self.faculty_cs_2.username), None)
        self.assertIsNotNone(self_row)
        self.assertIsNotNone(other_row)

        # Faculty can view details of self, but NOT of other faculty
        self.assertTrue(self_row['can_view_details'])
        self.assertFalse(other_row['can_view_details'])
        self.assertEqual(self_row['achievements_count'], 1)
        self.assertEqual(self_row['approved_count'], 1)

        # Authenticate as CS coordinator
        self.client.force_authenticate(user=self.coordinator_cs)
        res_coord = self.client.get('/api/activities/user-summary/')
        self.assertEqual(res_coord.status_code, status.HTTP_200_OK)
        coord_data = res_coord.data

        cs_faculty_row = next((u for u in coord_data if u['username'] == self.faculty_cs_1.username), None)
        ai_faculty_row = next((u for u in coord_data if u['username'] == self.faculty_ai.username), None)

        # Coordinator can view details in their department (CSE), but NOT outside (AIDS)
        self.assertTrue(cs_faculty_row['can_view_details'])
        self.assertFalse(ai_faculty_row['can_view_details'])

        # Authenticate as Super Admin: can view all
        self.client.force_authenticate(user=self.admin_user)
        res_admin = self.client.get('/api/activities/user-summary/')
        admin_data = res_admin.data
        for u in admin_data:
            self.assertTrue(u['can_view_details'])

    def test_activity_query_by_username_permission_enforcement(self):
        """Querying ?username=<username> properly restricts access based on permissions."""
        # 1. Regular faculty querying self -> succeeds
        self.client.force_authenticate(user=self.faculty_cs_1)
        res_self = self.client.get(f'/api/activities/?username={self.faculty_cs_1.username}')
        self.assertEqual(res_self.status_code, status.HTTP_200_OK)
        self.assertGreater(len(res_self.data.get('results', res_self.data)), 0)

        # 2. Regular faculty querying another faculty -> blocked (returns empty list)
        res_other = self.client.get(f'/api/activities/?username={self.faculty_cs_2.username}')
        self.assertEqual(res_other.status_code, status.HTTP_200_OK)
        results = res_other.data.get('results', res_other.data)
        self.assertEqual(len(results), 0)

        # 3. Regular faculty attempting scope=all -> scope bypass blocked, only own returned
        res_scope = self.client.get('/api/activities/?scope=all')
        self.assertEqual(res_scope.status_code, status.HTTP_200_OK)
        scope_results = res_scope.data.get('results', res_scope.data)
        for act in scope_results:
            self.assertEqual(str(act['faculty']), str(self.faculty_cs_1.id))

        # 4. Department coordinator querying faculty in same department -> succeeds
        self.client.force_authenticate(user=self.coordinator_cs)
        res_coord_cs = self.client.get(f'/api/activities/?username={self.faculty_cs_1.username}')
        self.assertEqual(res_coord_cs.status_code, status.HTTP_200_OK)
        self.assertGreater(len(res_coord_cs.data.get('results', res_coord_cs.data)), 0)

        # 5. Department coordinator querying faculty in different department -> returns empty
        res_coord_ai = self.client.get(f'/api/activities/?username={self.faculty_ai.username}')
        self.assertEqual(res_coord_ai.status_code, status.HTTP_200_OK)
        coord_ai_results = res_coord_ai.data.get('results', res_coord_ai.data)
        self.assertEqual(len(coord_ai_results), 0)

        # 6. Admin querying any faculty -> succeeds
        self.client.force_authenticate(user=self.admin_user)
        res_admin_query = self.client.get(f'/api/activities/?username={self.faculty_ai.username}')
        self.assertEqual(res_admin_query.status_code, status.HTTP_200_OK)
        self.assertGreater(len(res_admin_query.data.get('results', res_admin_query.data)), 0)

    def test_dynamic_role_permission_without_static_role_names(self):
        """Verify dynamic permission evaluation for arbitrary/custom role names without static code checks."""
        # 1. Custom Institution Auditor role (name/code: 'custom_auditor', department=None, has activities:approve)
        role_auditor = Role.objects.create(name="Custom Auditor", code="custom_auditor")
        RolePermission.objects.create(
            role=role_auditor,
            module=self.mod_activities,
            can_view=True,
            can_create=False,
            can_edit=False,
            can_delete=False,
            can_approve=True,
            can_export=True,
        )
        user_auditor = User.objects.create_user(
            username="custom_auditor_user",
            email="auditor@poornima.org",
            password="password123",
            first_name="Custom",
            last_name="Auditor",
            department=None,  # institution-wide
            role=role_auditor
        )
        self.assertTrue(user_auditor.has_module_perm('activities', 'approve'))
        self.assertIsNone(user_auditor.department_id)

        # Check API response for custom_auditor
        self.client.force_authenticate(user=user_auditor)
        res_auditor = self.client.get('/api/activities/user-summary/')
        self.assertEqual(res_auditor.status_code, status.HTTP_200_OK)
        for u in res_auditor.data:
            self.assertTrue(u['can_view_details'])

        # Can query activities for both departments
        res_q1 = self.client.get(f'/api/activities/?username={self.faculty_cs_1.username}')
        self.assertEqual(res_q1.status_code, status.HTTP_200_OK)
        self.assertGreater(len(res_q1.data.get('results', res_q1.data)), 0)

        res_q2 = self.client.get(f'/api/activities/?username={self.faculty_ai.username}')
        self.assertEqual(res_q2.status_code, status.HTTP_200_OK)
        self.assertGreater(len(res_q2.data.get('results', res_q2.data)), 0)

        # 2. Custom Department Reviewer role (name/code: 'dept_quality_reviewer', department=dept_cs, has activities:approve)
        role_dept_rev = Role.objects.create(name="Dept Quality Reviewer", code="dept_quality_reviewer")
        RolePermission.objects.create(
            role=role_dept_rev,
            module=self.mod_activities,
            can_view=True,
            can_create=False,
            can_edit=False,
            can_delete=False,
            can_approve=True,
            can_export=False,
        )
        user_dept_rev = User.objects.create_user(
            username="custom_cs_reviewer",
            email="csrev@poornima.org",
            password="password123",
            first_name="Dept",
            last_name="Reviewer",
            department=self.dept_cs,  # Scoped to CSE
            role=role_dept_rev
        )
        self.assertTrue(user_dept_rev.has_module_perm('activities', 'approve'))
        self.assertEqual(user_dept_rev.department_id, self.dept_cs.id)

        # Check API response for custom_cs_reviewer
        self.client.force_authenticate(user=user_dept_rev)
        res_rev = self.client.get('/api/activities/user-summary/')
        self.assertEqual(res_rev.status_code, status.HTTP_200_OK)
        cs_item = next((x for x in res_rev.data if x['username'] == self.faculty_cs_1.username), None)
        ai_item = next((x for x in res_rev.data if x['username'] == self.faculty_ai.username), None)
        self.assertTrue(cs_item['can_view_details'])
        self.assertFalse(ai_item['can_view_details'])

        # Querying CS faculty works; querying AI faculty returns empty
        res_cs_act = self.client.get(f'/api/activities/?username={self.faculty_cs_1.username}')
        self.assertEqual(res_cs_act.status_code, status.HTTP_200_OK)
        self.assertGreater(len(res_cs_act.data.get('results', res_cs_act.data)), 0)
        res_ai_act = self.client.get(f'/api/activities/?username={self.faculty_ai.username}')
        self.assertEqual(res_ai_act.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_ai_act.data.get('results', res_ai_act.data)), 0)

    def test_superuser_and_admin_username_filtering(self):
        """
        Verify that when a superuser or admin queries GET /api/activities/?username=X&page_size=100,
        it strictly returns records belonging to user X and NOT records belonging to other users.
        """
        # Create superuser
        superuser = User.objects.create_superuser(
            username="test_platform_superuser",
            email="super@platform.org",
            password="password123"
        )
        self.client.force_authenticate(user=superuser)

        # Query specifically for faculty_cs_1
        res = self.client.get(f'/api/activities/?username={self.faculty_cs_1.username}&page_size=100')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        records = res.data.get('results', res.data)
        self.assertGreater(len(records), 0)
        for rec in records:
            # Must strictly belong to faculty_cs_1
            fac_id = rec['faculty']['id'] if isinstance(rec['faculty'], dict) else rec['faculty']
            self.assertEqual(str(fac_id), str(self.faculty_cs_1.id))

        # Query specifically for faculty_ai
        res_ai = self.client.get(f'/api/activities/?username={self.faculty_ai.username}&page_size=100')
        self.assertEqual(res_ai.status_code, status.HTTP_200_OK)
        records_ai = res_ai.data.get('results', res_ai.data)
        self.assertGreater(len(records_ai), 0)
        for rec in records_ai:
            fac_id = rec['faculty']['id'] if isinstance(rec['faculty'], dict) else rec['faculty']
            self.assertEqual(str(fac_id), str(self.faculty_ai.id))










