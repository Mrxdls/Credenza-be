import os
import zipfile
import tempfile
import logging
from typing import Dict, Any, List
import openpyxl
from django.db import transaction
from django.core.files import File
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.accounts.models import Department, Designation, Role
from apps.activities.models import AcademicSession, Activity, ActivityAuthor, ActivityStatus, ActivityType
from apps.documents.models import ActivityDocument, DocumentType

logger = logging.getLogger(__name__)
User = get_user_model()


class BulkIngestionService:
    """
    Robust, in-memory pre-validated bulk ingestion engine for faculty achievements.
    Handles real-world messy spreadsheets including wrapped rows and empty placeholders.
    """

    @classmethod
    def clean_emp_id(cls, raw_val) -> str:
        if raw_val is None:
            return ""
        s = str(raw_val).strip()
        if s.endswith('.0'):
            s = s[:-2]
        return s

    @classmethod
    def resolve_or_create_faculty(cls, name: str, emp_id: str, dept_raw: str = "", desig_raw: str = "") -> User:
        """Finds or creates a faculty user record matching the spreadsheet row."""
        emp_id_clean = cls.clean_emp_id(emp_id)
        name_clean = str(name).strip() if name else "Faculty Member"

        user = None
        if emp_id_clean:
            user = User.objects.filter(employee_id=emp_id_clean).first()

        if not user and name_clean:
            parts = name_clean.split()
            first_name = parts[0]
            last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
            user = User.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name).first()

        # Resolve Department
        department = None
        if dept_raw:
            dept_str = str(dept_raw).strip()
            department = Department.objects.filter(name__iexact=dept_str).first() or \
                         Department.objects.filter(code__iexact=dept_str).first() or \
                         Department.objects.filter(name__icontains=dept_str).first()
            if not department:
                code_cand = dept_str[:10].upper()
                department, _ = Department.objects.get_or_create(
                    code=code_cand,
                    defaults={'name': dept_str}
                )

        # Resolve Designation
        designation = None
        if desig_raw:
            desig_str = str(desig_raw).strip()
            designation = Designation.objects.filter(name__iexact=desig_str).first()
            if not designation:
                designation, _ = Designation.objects.get_or_create(
                    name=desig_str,
                    defaults={'priority': 30}
                )

        if not user:
            username_base = emp_id_clean or name_clean.lower().replace(" ", ".")[:20]
            username = username_base
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{username_base}_{counter}"
                counter += 1

            parts = name_clean.split()
            faculty_role = Role.objects.filter(code='faculty').first()
            user = User.objects.create(
                username=username,
                employee_id=emp_id_clean or None,
                first_name=parts[0] if parts else "Faculty",
                last_name=" ".join(parts[1:]) if len(parts) > 1 else "",
                department=department,
                designation=designation,
                role=faculty_role,
                email=f"{username}@poornima.org",
                is_active=True,
                is_staff=True,
            )
            user.set_password("poornima123")
            user.save()
        else:
            updated = False
            if not user.is_staff:
                user.is_staff = True
                updated = True
            if not user.role:
                user.role = Role.objects.filter(code='faculty').first()
                updated = True
            if department and not user.department:
                user.department = department
                updated = True
            if designation and not user.designation:
                user.designation = designation
                updated = True
            if emp_id_clean and not user.employee_id:
                user.employee_id = emp_id_clean
                updated = True
            if updated:
                user.save()

        return user

    @classmethod
    def resolve_session(cls, raw_session_str: str = "", default_session_id=None) -> AcademicSession:
        if default_session_id:
            session = AcademicSession.objects.filter(id=default_session_id).first()
            if session:
                return session

        sess_str = str(raw_session_str).strip() if raw_session_str else "2025-2026"
        if "2025" in sess_str or "25-26" in sess_str:
            name = "2025-2026"
        elif "2026" in sess_str or "26-27" in sess_str:
            name = "2026-2027"
        else:
            name = sess_str

        session, _ = AcademicSession.objects.get_or_create(
            name=name,
            defaults={
                'start_date': '2025-07-01',
                'end_date': '2026-06-30',
                'is_current': True
            }
        )
        return session

    @classmethod
    def detect_format_from_headers(cls, headers: List[str], filename_or_sheet: str = "") -> str:
        hint = filename_or_sheet.lower()
        if "patent" in hint:
            return ActivityType.PATENT
        if "participation" in hint or "fdp" in hint:
            return ActivityType.FACULTY_PARTICIPATION
        if "conference" in hint:
            return ActivityType.CONFERENCE_PUBLICATION
        if "journal" in hint:
            return ActivityType.JOURNAL_PUBLICATION

        header_text = " ".join([str(h).lower() for h in headers if h])
        if "patent" in header_text or "application number" in header_text:
            return ActivityType.PATENT
        if "title of the program" in header_text or "duration of the program" in header_text or "start date" in header_text:
            return ActivityType.FACULTY_PARTICIPATION
        if "proceedings" in header_text or ("conference" in header_text and "type of program" not in header_text):
            return ActivityType.CONFERENCE_PUBLICATION
        if "journal" in header_text:
            return ActivityType.JOURNAL_PUBLICATION
        return ActivityType.JOURNAL_PUBLICATION

    @classmethod
    def parse_workbook(cls, file_obj, filename: str = "") -> List[Dict[str, Any]]:
        wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
        all_records = []
        name_hint = filename or getattr(file_obj, 'name', '')

        for sheetname in wb.sheetnames:
            sheet = wb[sheetname]
            rows_iter = sheet.iter_rows(values_only=True)
            
            # Find header row
            header_row = None
            header_idx = 0
            for i, row in enumerate(rows_iter):
                row_str = " ".join([str(c).lower() for c in row if c is not None])
                if any(kw in row_str for kw in ("name of faculty", "sr. no.", "s. no.", "title of publictaion", "title of the program")):
                    header_row = [str(c).strip().replace('\n', ' ') if c is not None else "" for c in row]
                    header_idx = i
                    break

            if not header_row:
                continue

            detected_type = cls.detect_format_from_headers(header_row, filename_or_sheet=f"{name_hint}_{sheetname}")

            # Accumulate rows with multi-line wrap stitching
            current_record = None

            for r_idx, row in enumerate(rows_iter, start=header_idx + 2):
                row_vals = [str(c).strip() if c is not None else "" for c in row]
                non_empty_vals = [v for v in row_vals if v]
                
                # Check if completely empty
                if not non_empty_vals:
                    continue

                # Map to header names
                row_dict = {}
                for col_idx, h_name in enumerate(header_row):
                    val = row_vals[col_idx] if col_idx < len(row_vals) else ""
                    if val:
                        row_dict[h_name] = val

                s_no = cls._find_value(row_dict, ["S. No.", "Sr. No.", "S.No."])
                faculty_name = cls._find_value(row_dict, ["Name of Faculty", "Name of the Teacher"])
                title = cls._find_value(row_dict, ["Title of Publictaion", "Title of the Program", "Title of Patent", "Title of the Paper", "Title"])

                # Check if row is just a number placeholder (e.g. S.No = '4.0' and everything else empty)
                if s_no and not faculty_name and not title and len(non_empty_vals) == 1:
                    continue

                # Check if row is a continuation of previous row (e.g. wrapped author or wrapped title)
                if current_record and (not s_no or not faculty_name) and (not title or title.startswith("for ") or "early disease" in title.lower()):
                    # Stitch wrapped text into current record
                    extra_text = " ".join(non_empty_vals)
                    if "authors_text" in current_record:
                        current_record["authors_text"] += f", {extra_text}"
                    if title and current_record.get("title"):
                        current_record["title"] += f" {title}"
                    continue

                # Valid new record
                if title or faculty_name:
                    emp_id = cls._find_value(row_dict, ["Emp. Id", "Employee ID", "Employee Id", "Emp Id"])
                    dept_raw = cls._find_value(row_dict, ["Deparment", "Department", "Dept"])
                    desig_raw = cls._find_value(row_dict, ["Current Designation", "Designation"])
                    session_raw = cls._find_value(row_dict, ["Session", "Academic Session"])
                    authors_text = cls._find_value(row_dict, ["Authors name in sequence as shown in publication", "Authors name in sequence as shown in pub", "Authors"])

                    metadata = {}
                    for k, v in row_dict.items():
                        if v:
                            clean_k = k.lower().replace(" ", "_").replace(".", "").replace("/", "_")[:40]
                            metadata[clean_k] = v

                    rec = {
                        "sheet": sheetname,
                        "row_num": r_idx,
                        "activity_type": detected_type,
                        "title": title or f"Activity by {faculty_name}",
                        "faculty_name": faculty_name,
                        "emp_id": emp_id,
                        "dept_raw": dept_raw,
                        "desig_raw": desig_raw,
                        "session_raw": session_raw,
                        "metadata": metadata,
                        "authors_text": authors_text,
                    }
                    all_records.append(rec)
                    current_record = rec

        return all_records

    @classmethod
    def process_xlsx(cls, file_obj, default_status=ActivityStatus.SUBMITTED, default_session_id=None, filename: str = "") -> Dict[str, Any]:
        """In-memory pre-pass validation followed by atomic database transaction."""
        valid_records = cls.parse_workbook(file_obj, filename=filename)
        if not valid_records:
            return {"success": False, "error": "No valid data rows found in workbook."}

        created_count = 0
        updated_count = 0
        skipped_count = 0

        with transaction.atomic():
            for rec in valid_records:
                faculty = cls.resolve_or_create_faculty(
                    rec["faculty_name"],
                    rec["emp_id"],
                    rec["dept_raw"],
                    rec["desig_raw"]
                )
                session = cls.resolve_session(rec["session_raw"], default_session_id)

                existing = Activity.objects.filter(
                    faculty=faculty,
                    academic_session=session,
                    activity_type=rec["activity_type"],
                    title__iexact=rec["title"]
                ).first()

                if existing:
                    if existing.status in (ActivityStatus.APPROVED,):
                        skipped_count += 1
                        continue
                    existing.metadata.update(rec["metadata"])
                    existing.save()
                    updated_count += 1
                    activity = existing
                else:
                    activity = Activity.objects.create(
                        faculty=faculty,
                        academic_session=session,
                        activity_type=rec["activity_type"],
                        title=rec["title"],
                        status=default_status,
                        metadata=rec["metadata"],
                    )
                    created_count += 1

                # Authors
                authors_text = rec["authors_text"]
                if authors_text:
                    author_names = [a.strip() for a in authors_text.replace(";", ",").split(",") if a.strip()]
                    for order, name in enumerate(author_names, 1):
                        ActivityAuthor.objects.get_or_create(
                            activity=activity,
                            author_order=order,
                            defaults={
                                'author_name': name,
                                'is_corresponding': (order == 1)
                            }
                        )

        return {
            "success": True,
            "created": created_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "total_processed": len(valid_records)
        }

    @classmethod
    def process_zip(cls, zip_file_obj, default_status=ActivityStatus.SUBMITTED, default_session_id=None) -> Dict[str, Any]:
        """
        Unpacks ZIP archive to a temporary scratch location.
        Requires one .xlsx file at root, and an optional proofs/ directory.
        Atomically ingests rows and links proof attachments.
        """
        with tempfile.TemporaryDirectory() as scratch_dir:
            try:
                with zipfile.ZipFile(zip_file_obj, 'r') as z:
                    z.extractall(scratch_dir)
            except Exception as e:
                return {"success": False, "error": f"Invalid zip archive: {str(e)}"}

            # Find .xlsx workbook at root
            xlsx_files = [f for f in os.listdir(scratch_dir) if f.lower().endswith('.xlsx') and not f.startswith('~$')]
            if not xlsx_files:
                return {"success": False, "error": "No .xlsx file found in the root of the ZIP archive."}

            xlsx_path = os.path.join(scratch_dir, xlsx_files[0])
            with open(xlsx_path, 'rb') as xf:
                records = cls.parse_workbook(xf)

            if not records:
                return {"success": False, "error": "No valid data rows found in the uploaded workbook."}

            # Pre-pass proof document validation
            proofs_dir = os.path.join(scratch_dir, "proofs")
            proof_files_map = {}
            if os.path.exists(proofs_dir):
                for fname in os.listdir(proofs_dir):
                    proof_files_map[fname.lower()] = os.path.join(proofs_dir, fname)

            # Atomic database transaction
            created_count = 0
            docs_linked = 0

            with transaction.atomic():
                for rec in records:
                    faculty = cls.resolve_or_create_faculty(
                        rec["faculty_name"],
                        rec["emp_id"],
                        rec["dept_raw"],
                        rec["desig_raw"]
                    )
                    session = cls.resolve_session(rec["session_raw"], default_session_id)

                    activity = Activity.objects.create(
                        faculty=faculty,
                        academic_session=session,
                        activity_type=rec["activity_type"],
                        title=rec["title"],
                        status=default_status,
                        metadata=rec["metadata"],
                    )
                    created_count += 1

                    # Check for proof attachment in metadata
                    proof_filename = rec["metadata"].get("proof_filename") or \
                                     rec["metadata"].get("file_name") or \
                                     rec["metadata"].get("please_attach_the_folder_in_which_pa")

                    if proof_filename and str(proof_filename).lower() in proof_files_map:
                        local_path = proof_files_map[str(proof_filename).lower()]
                        with open(local_path, 'rb') as pf:
                            doc = ActivityDocument(
                                activity=activity,
                                document_type=DocumentType.PUBLISHED_PAPER,
                                title=os.path.basename(local_path),
                                is_verified=True,
                            )
                            doc.file.save(os.path.basename(local_path), File(pf), save=True)
                            docs_linked += 1

            return {
                "success": True,
                "activities_created": created_count,
                "documents_linked": docs_linked,
                "total_rows": len(records)
            }

    @classmethod
    def _find_value(cls, data: dict, candidates: List[str]) -> str:
        for c in candidates:
            if c in data and data[c]:
                return str(data[c]).strip()
        data_lower = {k.lower(): v for k, v in data.items()}
        for c in candidates:
            if c.lower() in data_lower and data_lower[c.lower()]:
                return str(data_lower[c.lower()]).strip()
        return ""
