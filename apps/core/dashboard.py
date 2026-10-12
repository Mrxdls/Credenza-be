from django.utils.translation import gettext_lazy as _
from apps.activities.models import Activity, ActivityStatus, ActivityType
from apps.documents.models import ActivityDocument
from apps.accounts.models import User, Department


def is_coordinator_or_above(request):
    """Checks if the user has coordinator, reviewer, HOD, Dean, or Admin privileges."""
    user = request.user
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if hasattr(user, 'get_rank') and user.get_rank() >= 30:
        return True
    if hasattr(user, 'has_module_perm') and user.has_module_perm('activities', 'approve'):
        return True
    if getattr(user, 'is_coordinator', False) or getattr(user, 'is_department_head', False):
        return True
    return False


def is_admin_or_hod(request):
    """Checks if the user has HOD, Dean, or Organization Admin privileges."""
    user = request.user
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if hasattr(user, 'get_rank') and user.get_rank() >= 50:
        return True
    if getattr(user, 'is_department_head', False):
        return True
    return False


def is_superuser_only(request):
    """Restricts access strictly to root Superusers (is_superuser=True)."""
    user = request.user
    return bool(user and user.is_authenticated and user.is_superuser)



def dashboard_callback(request, context):
    """
    Supplies custom KPI cards and breakdown metrics to the Unfold Admin index page.
    Automatically adapts metrics dynamically using scope ('self', 'department', 'organization')
    and rank, completely agnostic of static role names.
    """
    user = request.user
    activities_qs = Activity.objects.all()

    if not user.is_superuser and getattr(user, 'tenant_id', None):
        activities_qs = activities_qs.filter(tenant_id=user.tenant_id)

    is_faculty = False
    if not user.is_superuser:
        user_scope = user.get_scope() if hasattr(user, 'get_scope') else 'self'
        if user_scope == 'department' and user.department:
            activities_qs = activities_qs.filter(faculty__department=user.department)
        elif user_scope == 'self':
            activities_qs = activities_qs.filter(faculty=user)
            is_faculty = True

    total_activities = activities_qs.count()
    pending_review = activities_qs.filter(status__in=[ActivityStatus.SUBMITTED, ActivityStatus.UNDER_REVIEW]).count()
    approved_activities = activities_qs.filter(status=ActivityStatus.APPROVED).count()
    total_proofs = ActivityDocument.objects.filter(activity__in=activities_qs).count()

    # Activity by Type breakdown
    journals = activities_qs.filter(activity_type=ActivityType.JOURNAL_PUBLICATION).count()
    conferences = activities_qs.filter(activity_type=ActivityType.CONFERENCE_PUBLICATION).count()
    patents = activities_qs.filter(activity_type=ActivityType.PATENT).count()
    fdps = activities_qs.filter(activity_type=ActivityType.FACULTY_PARTICIPATION).count()

    if is_faculty:
        card_1_title = _("My Submissions")
        card_1_footer = _("Total submitted by you")
        card_2_title = _("Under Review")
        card_2_footer = _("Awaiting verification")
        card_3_title = _("Approved & Verified")
        card_3_footer = _("Accreditation-ready")
        card_4_title = _("Attached Proofs")
        card_4_footer = _("Certificates & reprints")
    else:
        card_1_title = _("Total Achievements")
        card_1_footer = _("Total records tracked")
        card_2_title = _("Pending Verification")
        card_2_footer = _("Needs coordinator review")
        card_3_title = _("Verified & Approved")
        card_3_footer = _("NAAC/NIRF audit-ready")
        card_4_title = _("Proof Documents")
        card_4_footer = _("Attached evidence files")

    context.update({
        "kpi_cards": [
            {
                "title": card_1_title,
                "metric": total_activities,
                "footer": card_1_footer,
            },
            {
                "title": card_2_title,
                "metric": pending_review,
                "footer": card_2_footer,
            },
            {
                "title": card_3_title,
                "metric": approved_activities,
                "footer": card_3_footer,
            },
            {
                "title": card_4_title,
                "metric": total_proofs,
                "footer": card_4_footer,
            },
        ],
        "type_breakdown": {
            "journals": journals,
            "conferences": conferences,
            "patents": patents,
            "fdps": fdps,
        },
        "is_faculty": is_faculty,
        "recent_activities": activities_qs.select_related('faculty', 'academic_session').order_by('-created_at')[:8],
    })
    return context
