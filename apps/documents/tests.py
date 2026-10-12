import io
import os
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import User, Department, Designation, Role, Module, RolePermission
from apps.activities.models import AcademicSession, Activity, ActivityType, ActivityStatus
from apps.documents.models import ActivityDocument, DocumentType
from apps.documents.storage import get_runtime_storage, format_file_size
from apps.documents.compression import (
    compress_and_store,
    decompress_and_fetch,
    is_zstd_compressed,
)


class DocumentStorageFunctionTests(TestCase):
    def test_store_and_fetch_with_bytes(self):
        sample_data = b"%PDF-1.4 sample PDF body content repeated " * 50
        result = compress_and_store(sample_data, "proofs/test_cert.pdf")

        # Native uncompressed storage
        self.assertFalse(result["storage_path"].endswith(".zst"))
        self.assertEqual(result["original_size"], len(sample_data))
        self.assertEqual(result["file_size"], len(sample_data))

        # Fetch and verify
        fetched_bytes, filename, mime_type = decompress_and_fetch(result["storage_path"])
        self.assertEqual(fetched_bytes, sample_data)
        self.assertEqual(filename, "test_cert.pdf")
        self.assertEqual(mime_type, "application/pdf")

        # Cleanup
        default_storage.delete(result["storage_path"])

    def test_store_and_fetch_with_uploaded_file(self):
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000
        uploaded = SimpleUploadedFile("award.png", image_bytes, content_type="image/png")

        result = compress_and_store(uploaded, "proofs/award.png")
        self.assertFalse(result["storage_path"].endswith(".zst"))
        self.assertEqual(result["original_name"], "award.png")

        fetched_bytes, fname, mime = decompress_and_fetch(result["storage_path"])
        self.assertEqual(fetched_bytes, image_bytes)
        self.assertEqual(fname, "award.png")
        self.assertEqual(mime, "image/png")

        default_storage.delete(result["storage_path"])

    def test_format_file_size(self):
        self.assertEqual(format_file_size(0), "0 B")
        self.assertEqual(format_file_size(500), "500 B")
        self.assertEqual(format_file_size(2048), "2.0 KB")
        self.assertEqual(format_file_size(1048576 * 3), "3.0 MB")


class ActivityDocumentIntegrationTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Computer Science", code="CSE")
        self.desig = Designation.objects.create(name="Professor", code="PROF", priority=10)
        self.role_fac = Role.objects.create(name="Faculty", code="faculty")
        self.role_coord = Role.objects.create(name="Coordinator", code="coordinator")
        self.role_admin = Role.objects.create(name="Admin", code="super_admin")

        self.mod_activities = Module.objects.create(name="Activities", code="activities")
        self.mod_documents = Module.objects.create(name="Documents", code="documents")

        for r in [self.role_fac, self.role_coord, self.role_admin]:
            RolePermission.objects.create(role=r, module=self.mod_activities, can_view=True, can_create=True)
            RolePermission.objects.create(role=r, module=self.mod_documents, can_view=True, can_create=True)

        self.faculty = User.objects.create_user(
            username="test_faculty",
            email="faculty@poornima.org",
            password="password123",
            department=self.dept,
            role=self.role_fac,
            is_staff=True
        )

        self.other_faculty = User.objects.create_user(
            username="other_faculty",
            email="other@poornima.org",
            password="password123",
            role=self.role_fac,
            is_staff=True
        )

        self.session = AcademicSession.objects.create(
            name="2025-2026",
            start_date="2025-07-01",
            end_date="2026-06-30",
            is_current=True
        )

        self.activity = Activity.objects.create(
            faculty=self.faculty,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="AI in Education Paper",
            status=ActivityStatus.SUBMITTED
        )

        self.client = APIClient()

    def test_model_save_stores_uploaded_proof_natively_without_compression(self):
        pdf_content = b"%PDF-1.4\n" + b"Academic publication proof document text " * 100
        uploaded_file = SimpleUploadedFile("ieee_paper.pdf", pdf_content, content_type="application/pdf")

        doc = ActivityDocument.objects.create(
            activity=self.activity,
            document_type=DocumentType.PUBLISHED_PAPER,
            title="Published Reprint",
            file=uploaded_file
        )

        # Invariant checks: Native uncompressed storage
        self.assertFalse(doc.file.name.endswith(".zst"))
        self.assertTrue(doc.file.name.endswith(".pdf"))
        self.assertEqual(doc.file_size, len(pdf_content))
        self.assertEqual(doc.file_name, "ieee_paper.pdf")
        self.assertEqual(doc.mime_type, "application/pdf")
        self.assertIn("KB", doc.formatted_size)

        # Verify fetching raw bytes
        file_bytes, name, mime = doc.get_file_bytes()
        self.assertEqual(file_bytes, pdf_content)
        self.assertEqual(name, "ieee_paper.pdf")
        self.assertEqual(mime, "application/pdf")

        # Cleanup
        if doc.file:
            doc.file.delete(save=False)

    def test_api_view_file_streams_raw_content_to_client(self):
        pdf_content = b"%PDF-1.4\n" + b"Conference Proceedings Certificate " * 80
        uploaded_file = SimpleUploadedFile("certificate.pdf", pdf_content, content_type="application/pdf")

        doc = ActivityDocument.objects.create(
            activity=self.activity,
            document_type=DocumentType.FDP_ATTENDANCE_CERTIFICATE,
            title="Attendance Certificate",
            file=uploaded_file
        )

        # 1. Faculty member fetches their own proof -> 302 redirect to Cloudflare R2 presigned URL
        self.client.force_authenticate(user=self.faculty)
        res = self.client.get(f"/api/documents/{doc.id}/view_file/")
        if res.status_code == status.HTTP_302_FOUND:
            self.assertIn("r2.cloudflarestorage.com", res.url)
            self.assertEqual(res["X-Content-Type-Options"], "nosniff")
            # Verify stream=1 parameter delivers raw content
            res_stream = self.client.get(f"/api/documents/{doc.id}/view_file/?stream=1")
            self.assertEqual(res_stream.status_code, status.HTTP_200_OK)
            self.assertEqual(res_stream.content, pdf_content)
            self.assertEqual(res_stream["Content-Type"], "application/pdf")
        else:
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertEqual(res.content, pdf_content)
            self.assertEqual(res["Content-Type"], "application/pdf")

        # 2. Download parameter -> sets attachment disposition
        res_dl = self.client.get(f"/api/documents/{doc.id}/view_file/?download=1")
        if res_dl.status_code == status.HTTP_302_FOUND:
            self.assertIn("response-content-disposition=attachment", res_dl.url.lower())
        else:
            self.assertEqual(res_dl.status_code, status.HTTP_200_OK)
            self.assertIn('attachment', res_dl["Content-Disposition"].lower())

        # 3. Other faculty member cannot view this proof -> 404 (scoped out)
        self.client.force_authenticate(user=self.other_faculty)
        res_other = self.client.get(f"/api/documents/{doc.id}/view_file/")
        self.assertEqual(res_other.status_code, status.HTTP_404_NOT_FOUND)

        if doc.file:
            doc.file.delete(save=False)


class CloudflareR2StorageTests(TestCase):
    def test_r2_config_resolution(self):
        from apps.documents.r2 import get_r2_config

        with patch.object(settings, 'CLOUDFLARE_ACCOUNT_ID', 'test-cf-account-id-12345'), \
             patch.object(settings, 'CLOUDFLARE_R2_BUCKET', 'test-poornima-r2'), \
             patch.object(settings, 'CLOUDFLARE_R2_PUBLIC_DOMAIN', 'https://cdn.poornima.edu'), \
             patch.object(settings, 'CLOUDFLARE_R2_ACCESS_KEY_ID', 'test-env-r2-key'), \
             patch.object(settings, 'CLOUDFLARE_R2_SECRET_ACCESS_KEY', 'test-env-r2-secret'):
            r2_cfg = get_r2_config()
            self.assertEqual(r2_cfg["account_id"], "test-cf-account-id-12345")
            self.assertEqual(r2_cfg["bucket_name"], "test-poornima-r2")
            self.assertEqual(r2_cfg["access_key_id"], "test-env-r2-key")
            self.assertEqual(r2_cfg["secret_access_key"], "test-env-r2-secret")
            self.assertEqual(r2_cfg["endpoint_url"], "https://test-cf-account-id-12345.r2.cloudflarestorage.com")
            self.assertEqual(r2_cfg["public_domain"], "https://cdn.poornima.edu")

    def test_store_and_fetch_from_r2_mocked(self):
        from apps.documents.r2 import store_to_r2, fetch_from_r2

        mock_s3 = MagicMock()
        mock_config = {
            "account_id": "test-account",
            "bucket_name": "test-bucket",
            "access_key_id": "key",
            "secret_access_key": "secret",
            "endpoint_url": "https://test-account.r2.cloudflarestorage.com",
            "public_domain": "",
            "presigned_expiry": 3600,
        }

        # Store test: Native raw storage without compression
        content = b"%PDF-1.4 Mocked Cloudflare R2 Paper " * 30
        res = store_to_r2(
            content,
            "proofs/r2_test.pdf",
            client=mock_s3,
            config=mock_config
        )

        self.assertEqual(res["storage_path"], "proofs/r2_test.pdf")
        self.assertEqual(res["bucket"], "test-bucket")
        self.assertEqual(res["file_size"], len(content))
        mock_s3.put_object.assert_called_once()
        put_kwargs = mock_s3.put_object.call_args[1]
        self.assertEqual(put_kwargs["Bucket"], "test-bucket")
        self.assertEqual(put_kwargs["Key"], "proofs/r2_test.pdf")
        self.assertEqual(put_kwargs["Body"], content)

        # Fetch test: return the raw body
        mock_body = MagicMock()
        mock_body.read.return_value = content
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "Metadata": {"original-filename": "r2_test.pdf"}
        }

        file_bytes, fname, mime = fetch_from_r2(
            "proofs/r2_test.pdf",
            client=mock_s3,
            config=mock_config
        )
        self.assertEqual(file_bytes, content)
        self.assertEqual(fname, "r2_test.pdf")
        self.assertEqual(mime, "application/pdf")

    def test_get_r2_presigned_url_mocked(self):
        from apps.documents.r2 import get_r2_presigned_url

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://test-account.r2.cloudflarestorage.com/test-bucket/file.pdf?sig=123"

        mock_config = {
            "bucket_name": "test-bucket",
            "presigned_expiry": 1800,
        }

        url = get_r2_presigned_url(
            "proofs/file.pdf",
            expiry=1800,
            download=True,
            original_filename="final_paper.pdf",
            client=mock_s3,
            config=mock_config
        )
        self.assertIn("r2.cloudflarestorage.com", url)
        mock_s3.generate_presigned_url.assert_called_once()

    def test_r2_storage_service_oop_methods(self):
        from apps.documents.r2 import R2Config, R2StorageService

        config = R2Config(
            account_id="acc-123",
            bucket_name="test-bucket",
            access_key_id="key-123",
            secret_access_key="sec-123",
            endpoint_url="https://acc-123.r2.cloudflarestorage.com"
        )
        self.assertTrue(config.is_valid)

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://signed.put.url"
        mock_s3.head_object.return_value = {"ContentLength": 54321}

        service = R2StorageService(config=config, client=mock_s3)
        self.assertTrue(service.is_configured)

        # Presigned upload URL
        put_url = service.generate_presigned_upload_url("proofs/1/test.pdf", "application/pdf")
        self.assertEqual(put_url, "https://signed.put.url")
        mock_s3.generate_presigned_url.assert_called_once()

        # Head file
        head_res = service.head_file("proofs/1/test.pdf")
        self.assertEqual(head_res["ContentLength"], 54321)
        mock_s3.head_object.assert_called_once_with(Bucket="test-bucket", Key="proofs/1/test.pdf")

        # Test connection
        success, msg = service.test_connection()
        self.assertTrue(success)
        mock_s3.head_bucket.assert_called_once_with(Bucket="test-bucket")

    def test_native_document_storage_service(self):
        from apps.documents.compression import NativeDocumentStorageService

        mock_storage = MagicMock()
        mock_storage.save.return_value = "saved/path/file.pdf"

        res = NativeDocumentStorageService.store_native(b"Sample PDF bytes", "proofs/file.pdf", storage=mock_storage)
        self.assertEqual(res["storage_path"], "saved/path/file.pdf")
        self.assertEqual(res["file_size"], len(b"Sample PDF bytes"))
        self.assertFalse(res["is_compressed"])


class DocumentSecurityHardeningTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dept = Department.objects.create(name="Computer Engineering", code="CE")
        self.role_faculty = Role.objects.create(name="Faculty", code="faculty")
        self.role_coord = Role.objects.create(name="Coordinator", code="coordinator")

        self.mod_activities = Module.objects.create(name="Activities", code="activities")
        self.mod_documents = Module.objects.create(name="Documents", code="documents")

        # Permissions: faculty has create/view on activities and documents
        RolePermission.objects.create(
            role=self.role_faculty,
            module=self.mod_activities,
            can_view=True,
            can_create=True,
            can_edit=True
        )
        RolePermission.objects.create(
            role=self.role_faculty,
            module=self.mod_documents,
            can_view=True,
            can_create=True,
            can_edit=True
        )
        # Coordinator has approval on documents
        RolePermission.objects.create(
            role=self.role_coord,
            module=self.mod_documents,
            can_view=True,
            can_create=True,
            can_edit=True,
            can_approve=True
        )

        self.faculty_a = User.objects.create_user(
            username="sec_faculty_a",
            email="fa@poornima.org",
            password="password123",
            role=self.role_faculty,
            department=self.dept
        )
        self.faculty_b = User.objects.create_user(
            username="sec_faculty_b",
            email="fb@poornima.org",
            password="password123",
            role=self.role_faculty,
            department=self.dept
        )
        self.coord_user = User.objects.create_user(
            username="sec_coordinator",
            email="coord@poornima.org",
            password="password123",
            role=self.role_coord,
            department=self.dept,
            is_coordinator=True
        )

        self.session = AcademicSession.objects.create(
            name="2025-2026",
            start_date="2025-07-01",
            end_date="2026-06-30",
            is_current=True
        )

        self.act_a = Activity.objects.create(
            faculty=self.faculty_a,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Faculty A Publication",
            status=ActivityStatus.DRAFT
        )
        self.act_b = Activity.objects.create(
            faculty=self.faculty_b,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Faculty B Publication",
            status=ActivityStatus.DRAFT
        )

    def test_reject_svg_upload(self):
        """SVG file upload must be rejected to prevent Stored XSS."""
        self.client.force_authenticate(user=self.faculty_a)
        svg_content = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        f = SimpleUploadedFile("xss.svg", svg_content, content_type="image/svg+xml")
        res = self.client.post("/api/documents/", {
            "activity": str(self.act_a.id),
            "document_type": DocumentType.PUBLISHED_PAPER,
            "title": "SVG Exploit Attempt",
            "file": f
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", res.data)
        self.assertIn("prohibited", str(res.data["file"]))

    def test_reject_html_upload(self):
        """HTML file upload must be rejected."""
        self.client.force_authenticate(user=self.faculty_a)
        html_content = b'<html><body><script>alert(1)</script></body></html>'
        f = SimpleUploadedFile("page.html", html_content, content_type="text/html")
        res = self.client.post("/api/documents/", {
            "activity": str(self.act_a.id),
            "document_type": DocumentType.PUBLISHED_PAPER,
            "title": "HTML Exploit Attempt",
            "file": f
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", res.data)

    def test_reject_script_content_in_disguised_file(self):
        """Files disguised with allowed extensions containing script headers must be rejected."""
        self.client.force_authenticate(user=self.faculty_a)
        disguised_content = b'<!DOCTYPE html><html><script>steal_cookies()</script></html>'
        f = SimpleUploadedFile("disguised.pdf", disguised_content, content_type="application/pdf")
        res = self.client.post("/api/documents/", {
            "activity": str(self.act_a.id),
            "document_type": DocumentType.PUBLISHED_PAPER,
            "title": "Disguised PDF",
            "file": f
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Malicious or executable content detected", str(res.data))

    def test_is_verified_parameter_cannot_be_tampered(self):
        """Faculty cannot mark their own documents as verified during creation."""
        self.client.force_authenticate(user=self.faculty_a)
        pdf_content = b'%PDF-1.4 official certified research proof'
        f = SimpleUploadedFile("cert.pdf", pdf_content, content_type="application/pdf")
        res = self.client.post("/api/documents/", {
            "activity": str(self.act_a.id),
            "document_type": DocumentType.PUBLISHED_PAPER,
            "title": "Tampered Verification",
            "file": f,
            "is_verified": True
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        doc = ActivityDocument.objects.get(id=res.data["id"])
        self.assertFalse(doc.is_verified)

    def test_prevent_idor_document_attachment(self):
        """Faculty A cannot attach proof documents to Faculty B's activity."""
        self.client.force_authenticate(user=self.faculty_a)
        pdf_content = b'%PDF-1.4 legitimate paper content'
        f = SimpleUploadedFile("legit.pdf", pdf_content, content_type="application/pdf")
        res = self.client.post("/api/documents/", {
            "activity": str(self.act_b.id),
            "document_type": DocumentType.PUBLISHED_PAPER,
            "title": "IDOR Proof Document",
            "file": f
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("activity", res.data)
        self.assertIn("You do not have permission", str(res.data["activity"]))

    def test_prevent_attaching_documents_to_approved_activity(self):
        """Proof documents cannot be attached to an already approved achievement."""
        self.act_a.status = ActivityStatus.APPROVED
        self.act_a.save()

        self.client.force_authenticate(user=self.faculty_a)
        pdf_content = b'%PDF-1.4 legitimate paper content'
        f = SimpleUploadedFile("new_proof.pdf", pdf_content, content_type="application/pdf")
        res = self.client.post("/api/documents/", {
            "activity": str(self.act_a.id),
            "document_type": DocumentType.PUBLISHED_PAPER,
            "title": "Post-Approval Attachment",
            "file": f
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already been verified and locked", str(res.data))

    def test_view_file_enforces_nosniff_and_csp_headers(self):
        """view_file response must include X-Content-Type-Options: nosniff and restrictive CSP."""
        self.client.force_authenticate(user=self.faculty_a)
        pdf_content = b'%PDF-1.4 sample file for header inspection'
        doc = ActivityDocument.objects.create(
            activity=self.act_a,
            document_type=DocumentType.PUBLISHED_PAPER,
            title="Safe Paper",
            file=SimpleUploadedFile("safe.pdf", pdf_content, content_type="application/pdf")
        )
        res = self.client.get(f"/api/documents/{doc.id}/view_file/")
        self.assertIn(res.status_code, [status.HTTP_200_OK, status.HTTP_302_FOUND])
        self.assertEqual(res["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", res["Content-Security-Policy"])

    def test_cookie_security_settings(self):
        """Verify strict cookie flags in Django settings."""
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)


class Phase4PresignedPipelineTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dept = Department.objects.create(name="Computer Engineering", code="CE")
        self.role_faculty = Role.objects.create(name="Faculty", code="faculty")
        self.role_coord = Role.objects.create(name="Coordinator", code="coordinator")

        self.mod_activities = Module.objects.create(name="Activities", code="activities")
        self.mod_documents = Module.objects.create(name="Documents", code="documents")

        RolePermission.objects.create(
            role=self.role_faculty,
            module=self.mod_activities,
            can_view=True,
            can_create=True,
            can_edit=True
        )
        RolePermission.objects.create(
            role=self.role_faculty,
            module=self.mod_documents,
            can_view=True,
            can_create=True,
            can_edit=True
        )
        RolePermission.objects.create(
            role=self.role_coord,
            module=self.mod_documents,
            can_view=True,
            can_create=True,
            can_edit=True,
            can_approve=True
        )

        self.faculty_a = User.objects.create_user(
            username="r2_faculty_a",
            email="fa@poornima.org",
            password="password123",
            role=self.role_faculty,
            department=self.dept
        )
        self.faculty_b = User.objects.create_user(
            username="r2_faculty_b",
            email="fb@poornima.org",
            password="password123",
            role=self.role_faculty,
            department=self.dept
        )

        self.session = AcademicSession.objects.create(
            name="2025-2026",
            start_date="2025-07-01",
            end_date="2026-06-30",
            is_current=True
        )

        self.act_a = Activity.objects.create(
            faculty=self.faculty_a,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Faculty A Publication",
            status=ActivityStatus.DRAFT
        )
        self.act_b = Activity.objects.create(
            faculty=self.faculty_b,
            academic_session=self.session,
            activity_type=ActivityType.JOURNAL_PUBLICATION,
            title="Faculty B Publication",
            status=ActivityStatus.DRAFT
        )

    def test_presigned_upload_url_generation(self):
        """Requesting presigned upload URL returns 200 with document_id, upload_url, and PUT method."""
        self.client.force_authenticate(user=self.faculty_a)
        payload = {
            "activity": str(self.act_a.id),
            "document_type": DocumentType.PUBLISHED_PAPER,
            "title": "IEEE Accepted Manuscript",
            "file_name": "ieee_paper.pdf",
            "file_size": 1048576,
            "mime_type": "application/pdf"
        }
        res = self.client.post("/api/documents/presigned-upload-url/", payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("upload_url", res.data)
        self.assertIn("document_id", res.data)
        self.assertEqual(res.data["method"], "PUT")
        self.assertIn("storage_path", res.data)

        # Document record created in DB
        doc = ActivityDocument.objects.get(id=res.data["document_id"])
        self.assertFalse(doc.is_verified)
        self.assertEqual(doc.file_name, "ieee_paper.pdf")
        self.assertEqual(doc.file_size, 1048576)

    def test_presigned_upload_url_idor_block(self):
        """Faculty cannot request presigned upload URL for another faculty's activity."""
        self.client.force_authenticate(user=self.faculty_a)
        payload = {
            "activity": str(self.act_b.id),
            "document_type": DocumentType.PUBLISHED_PAPER,
            "file_name": "attack.pdf",
            "file_size": 1024,
            "mime_type": "application/pdf"
        }
        res = self.client.post("/api/documents/presigned-upload-url/", payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_presigned_upload_url_reject_invalid_extension(self):
        """Presigned upload URL generation rejects prohibited extensions."""
        self.client.force_authenticate(user=self.faculty_a)
        payload = {
            "activity": str(self.act_a.id),
            "file_name": "malicious.html",
            "file_size": 1024,
        }
        res = self.client.post("/api/documents/presigned-upload-url/", payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("prohibited", str(res.data))

    def test_presigned_upload_url_reject_approved_activity(self):
        """Presigned upload URL generation is blocked for approved activities."""
        self.act_a.status = ActivityStatus.APPROVED
        self.act_a.save()

        self.client.force_authenticate(user=self.faculty_a)
        payload = {
            "activity": str(self.act_a.id),
            "file_name": "paper.pdf",
            "file_size": 1024,
        }
        res = self.client.post("/api/documents/presigned-upload-url/", payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already been verified and locked", str(res.data))

    def test_confirm_upload_flow(self):
        """Confirm upload activates document and returns serialized document record."""
        self.client.force_authenticate(user=self.faculty_a)
        payload = {
            "activity": str(self.act_a.id),
            "file_name": "test_proof.pdf",
            "file_size": 2048,
            "mime_type": "application/pdf"
        }
        res_url = self.client.post("/api/documents/presigned-upload-url/", payload, format='json')
        doc_id = res_url.data["document_id"]

        # Client uploads bytes
        self.client.put(f"/api/documents/{doc_id}/upload-direct/", b"%PDF-1.4 test bytes", content_type="application/pdf")

        # Client confirms upload
        res_confirm = self.client.post(f"/api/documents/{doc_id}/confirm-upload/")
        self.assertEqual(res_confirm.status_code, status.HTTP_200_OK)
        self.assertEqual(res_confirm.data["id"], doc_id)

    @patch('apps.documents.views.is_r2_active', return_value=True)
    @patch('apps.documents.views.get_r2_presigned_url', return_value="https://test.r2.cloudflarestorage.com/proof.pdf?signed=1")
    def test_view_file_r2_zero_egress_redirect(self, mock_presign, mock_is_r2):
        """view_file returns 302 redirect directly to signed Cloudflare R2 URL when R2 is active."""
        self.client.force_authenticate(user=self.faculty_a)
        doc = ActivityDocument.objects.create(
            activity=self.act_a,
            document_type=DocumentType.PUBLISHED_PAPER,
            title="R2 Paper",
            file_name="paper.pdf"
        )
        doc.file.name = "proofs/paper.pdf"
        doc.save(update_fields=['file'])

        res = self.client.get(f"/api/documents/{doc.id}/view_file/")
        self.assertEqual(res.status_code, status.HTTP_302_FOUND)
        self.assertEqual(res.url, "https://test.r2.cloudflarestorage.com/proof.pdf?signed=1")
        self.assertEqual(res["X-Content-Type-Options"], "nosniff")
        mock_presign.assert_called_once()

    def test_generate_r2_presigned_upload_url_mocked(self):
        """Unit test for generate_r2_presigned_upload_url."""
        from apps.documents.r2 import generate_r2_presigned_upload_url

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://test.r2.cloudflarestorage.com/bucket/key?put=1"
        mock_config = {
            "bucket_name": "test-bucket",
        }

        url = generate_r2_presigned_upload_url(
            "proofs/test.pdf",
            content_type="application/pdf",
            expiry=900,
            client=mock_s3,
            config=mock_config
        )
        self.assertEqual(url, "https://test.r2.cloudflarestorage.com/bucket/key?put=1")
        mock_s3.generate_presigned_url.assert_called_once()
        call_kwargs = mock_s3.generate_presigned_url.call_args[1]
        self.assertEqual(call_kwargs["ClientMethod"], "put_object")
        self.assertEqual(call_kwargs["Params"]["ContentType"], "application/pdf")


