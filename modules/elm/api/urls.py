"""URL routing configuration for ELM API endpoints."""
from django.urls import path

from modules.elm.api import views

app_name = "elm"

urlpatterns = [
    # Leaves
    path("leaves/", views.MyLeavesView.as_view(), name="my-leaves"),
    path("leaves/<int:pk>/", views.LeaveDetailWithdrawView.as_view(), name="leave-detail"),
    path("leaves/<int:pk>/cancel/", views.LeaveCancellationView.as_view(), name="leave-cancel"),
    path("leaves/<int:pk>/resume/", views.LeaveResumptionView.as_view(), name="leave-resume"),

    # Balances & Holidays
    path("balances/", views.MyBalancesView.as_view(), name="my-balances"),
    path("holidays/", views.HolidayCalendarView.as_view(), name="holidays"),

    # Workflows
    path("substitute/", views.SubstituteQueueView.as_view(), name="substitute-queue"),
    path("substitute/<int:pk>/respond/", views.SubstituteQueueView.as_view(), name="substitute-respond"),
    path("unit-head/", views.UnitHeadReviewView.as_view(), name="unit-head-queue"),
    path("unit-head/<int:pk>/review/", views.UnitHeadReviewView.as_view(), name="unit-head-review"),
    path("sanctions/", views.SanctionDecisionView.as_view(), name="sanctions-queue"),
    path("sanctions/<int:pk>/sanction/", views.SanctionDecisionView.as_view(), name="sanction-decision"),
]
