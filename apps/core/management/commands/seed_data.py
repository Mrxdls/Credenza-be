from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from apps.accounts.models import Department, Designation, Module, Role, RolePermission
from apps.activities.models import AcademicSession
User = get_user_model()


class Command(BaseCommand):
    help = "Seeds initial database entities: Modules, Roles, Permissions, Departments, Designations, Sessions, and Superuser."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting Poornima Portal Database Seeding..."))

        with transaction.atomic():
            # Purge obsolete/contradictory modules
            Module.objects.filter(code__in=["data_import", "data_export"]).delete()

            # 1. Seed Domain Modules
            modules_data = [
                {"name": "Faculty Achievements", "code": "activities", "description": "Manage publications, patents, and FDP achievements"},
                {"name": "Proof Documents", "code": "documents", "description": "Upload and manage verified evidence certificates"},
                {"name": "Accreditation & NAAC Reports", "code": "reports", "description": "Generate NAAC AQAR Criteria 3 and NIRF evaluation reports"},
                {"name": "User & Department Management", "code": "accounts", "description": "Manage faculty profiles, departments, and roles"},
            ]
            modules = {}
            for m_info in modules_data:
                mod, created = Module.objects.get_or_create(
                    code=m_info["code"],
                    defaults={"name": m_info["name"], "description": m_info["description"]}
                )
                modules[mod.code] = mod
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  + Module created: {mod.name}"))

            # 2. Seed Roles
            roles_data = [
                {"name": "Super Administrator", "code": "super_admin", "description": "Root system administrator with global permissions"},
                {"name": "Dean / Director", "code": "dean", "description": "University leadership with institution-wide view and export access"},
                {"name": "Head of Department (HOD)", "code": "hod", "description": "Departmental head with approval and oversight access"},
                {"name": "Department Data Coordinator", "code": "coordinator", "description": "Coordinator responsible for data ingestion, auditing, and verification"},
                {"name": "Faculty Member", "code": "faculty", "description": "Individual professor/researcher submitting achievements"},
            ]
            roles = {}
            for r_info in roles_data:
                role, created = Role.objects.get_or_create(
                    code=r_info["code"],
                    defaults={"name": r_info["name"], "description": r_info["description"]}
                )
                roles[role.code] = role
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  + Role created: {role.name}"))

            # 2b. Seed Default Django Auth Group
            from django.contrib.auth.models import Group
            default_group, g_created = Group.objects.get_or_create(name="Faculty")
            if g_created:
                self.stdout.write(self.style.SUCCESS(f"  + Default Auth Group created: {default_group.name}"))

            # 3. Seed Granular Role-Module Permissions
            default_none = {"view": False, "create": False, "edit": False, "delete": False, "approve": False, "export": False}
            all_true = {"view": True, "create": True, "edit": True, "delete": True, "approve": True, "export": True}

            role_module_matrix = {
                "super_admin": {
                    "activities": all_true,
                    "documents": all_true,
                    "reports": all_true,
                    "accounts": all_true,
                },
                "dean": {
                    "activities": {"view": True, "create": False, "edit": False, "delete": False, "approve": True, "export": True},
                    "documents": {"view": True, "create": False, "edit": False, "delete": False, "approve": True, "export": True},
                    "reports": {"view": True, "create": False, "edit": False, "delete": False, "approve": True, "export": True},
                    "accounts": {"view": True, "create": False, "edit": False, "delete": False, "approve": False, "export": False},
                },
                "hod": {
                    "activities": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
                    "documents": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
                    "reports": {"view": True, "create": False, "edit": False, "delete": False, "approve": True, "export": True},
                    "accounts": {"view": True, "create": False, "edit": False, "delete": False, "approve": False, "export": False},
                },
                "coordinator": {
                    "activities": {"view": True, "create": True, "edit": True, "delete": True, "approve": True, "export": True},
                    "documents": {"view": True, "create": True, "edit": True, "delete": True, "approve": True, "export": True},
                    "reports": {"view": True, "create": False, "edit": False, "delete": False, "approve": True, "export": True},
                    "accounts": {"view": True, "create": False, "edit": False, "delete": False, "approve": False, "export": False},
                },
                "faculty": {
                    "activities": {"view": True, "create": True, "edit": True, "delete": False, "approve": False, "export": True},
                    "documents": {"view": True, "create": True, "edit": True, "delete": False, "approve": False, "export": False},
                    "reports": {"view": True, "create": False, "edit": False, "delete": False, "approve": False, "export": True},
                    "accounts": {"view": False, "create": False, "edit": False, "delete": False, "approve": False, "export": False},
                },
            }

            for role_code, mod_perms in role_module_matrix.items():
                role = roles.get(role_code)
                for mod_code, perms in mod_perms.items():
                    mod = modules.get(mod_code)
                    if mod:
                        RolePermission.objects.update_or_create(
                            role=role,
                            module=mod,
                            defaults={
                                "can_view": perms.get("view", False),
                                "can_create": perms.get("create", False),
                                "can_edit": perms.get("edit", False),
                                "can_delete": perms.get("delete", False),
                                "can_approve": perms.get("approve", False),
                                "can_export": perms.get("export", False),
                            }
                        )
            self.stdout.write(self.style.SUCCESS("  + Granular Role-Module Permissions configured."))

            # 4. Seed Departments (scoped to Tenant)
            depts_data = [
                {"name": "Advance Computing", "code": "AC"},
                {"name": "Artificial Intelligence and Data Science", "code": "AD"},
                {"name": "Computer Engineering", "code": "CE"},
                {"name": "Computer Science and Engineering", "code": "CSE"},
                {"name": "Electronics and Communication Engineering", "code": "ECE"},
                {"name": "Electrical Engineering", "code": "EE"},
                {"name": "Mechanical Engineering", "code": "ME"},
                {"name": "Civil Engineering", "code": "CIVIL"},
                {"name": "Information Technology", "code": "IT"},
            ]
            departments = {}
            for d_info in depts_data:
                dept, created = Department.objects.get_or_create(
                    code=d_info["code"],
                    defaults={"name": d_info["name"]}
                )
                departments[dept.code] = dept
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  + Department created: {dept.name} ({dept.code})"))

            # 5. Seed Designations
            desigs_data = [
                {"name": "Professor", "code": "PROF", "priority": 10},
                {"name": "Associate Professor", "code": "ASSOC_PROF", "priority": 20},
                {"name": "Assistant Professor", "code": "ASST_PROF", "priority": 30},
                {"name": "Lecturer", "code": "LECT", "priority": 40},
            ]
            designations = {}
            for dg_info in desigs_data:
                desig, created = Designation.objects.get_or_create(
                    code=dg_info["code"],
                    defaults={"name": dg_info["name"], "priority": dg_info["priority"]}
                )
                designations[desig.name] = desig
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  + Designation created: {desig.name}"))

            # 6. Seed Academic Sessions
            sessions_data = [
                {"name": "2025-2026", "start": "2025-07-01", "end": "2026-06-30", "current": True},
                {"name": "2026-2027", "start": "2026-07-01", "end": "2027-06-30", "current": False},
            ]
            for s_info in sessions_data:
                sess, created = AcademicSession.objects.get_or_create(
                    name=s_info["name"],
                    defaults={
                        "start_date": s_info["start"],
                        "end_date": s_info["end"],
                        "is_current": s_info["current"]
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  + Academic Session created: {sess.name}"))

            # 7. Seed Administrative Users (Only DevOps Superadmin)
            admin_user, created = User.objects.get_or_create(
                username="admin",
                defaults={
                    "first_name": "System",
                    "last_name": "Administrator",
                    "email": "admin@poornima.org",
                    "is_staff": True,
                    "is_superuser": True,
                    "role": roles["super_admin"],
                }
            )
            if created:
                admin_user.set_password("admin123")
                admin_user.save()
                self.stdout.write(self.style.SUCCESS("  + Superuser created: admin / admin123"))

            # Attach default group to admin
            if not admin_user.groups.filter(id=default_group.id).exists():
                admin_user.groups.add(default_group)

        self.stdout.write(self.style.SUCCESS("\n[DONE] Database seeding completed successfully!"))
