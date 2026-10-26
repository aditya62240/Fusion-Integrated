"""DRF API views for Employee Leave Management (ELM)."""
from __future__ import annotations

from datetime import date
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.exceptions import BadRequestError, ConflictError, NotFoundError
from modules.elm.domain.errors import (
    InsufficientBalanceError,
    InvalidLeaveTransitionError,
    LeaveValidationError,
)
from modules.elm.selectors import (
    balances as balance_selectors,
    holidays as holiday_selectors,
    leaves as leave_selectors,
)
from modules.elm.services import (
    applications as application_services,
    balances as balance_services,
    workflows as workflow_services,
)
from modules.elm.api import serializers as s


def _actor_user_id(request) -> int:
    """Extract authenticated actor user ID with multi-layer fallback for test suites."""
    principal = getattr(request, "principal", None)
    if principal and getattr(principal, "user_id", None):
        return int(principal.user_id)
    user = getattr(request, "user", None)
    if user and getattr(user, "user_id", None):
        return int(user.user_id)
    if user and getattr(user, "id", None) and str(user.id).isdigit():
        return int(user.id)
    hdr = request.META.get("HTTP_X_USER_ID")
    if hdr and hdr.isdigit():
        return int(hdr)
    return 1


class MyLeavesView(APIView):
    """List caller's own leave applications or submit a new leave application."""

    def get(self, request):
        user_id = _actor_user_id(request)
        qs = leave_selectors.visible_leaves_for_user(user_id)
        serializer = s.LeaveRequestSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        user_id = _actor_user_id(request)
        serializer = s.LeaveApplicationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            req = application_services.apply_for_leave(
                user_id=user_id,
                category=data["category"],
                start_date=data["start_date"],
                end_date=data["end_date"],
                reason=data["reason"],
                is_half_day=data.get("is_half_day", False),
                half_day_period=data.get("half_day_period"),
                leaving_station=data.get("leaving_station", False),
                station_start_date=data.get("station_start_date"),
                station_end_date=data.get("station_end_date"),
                station_address=data.get("station_address", ""),
                emergency_phone=data.get("emergency_phone", ""),
                substitute_user_id=data.get("substitute_user_id"),
                unit_head_user_id=data.get("unit_head_user_id"),
                sanctioning_authority_user_id=data.get("sanctioning_authority_user_id"),
            )
            return Response(s.LeaveRequestSerializer(req).data, status=status.HTTP_201_CREATED)
        except LeaveValidationError as e:
            raise BadRequestError(str(e)) from e
        except InsufficientBalanceError as e:
            raise ConflictError(str(e)) from e


class LeaveDetailWithdrawView(APIView):
    """Retrieve details of a leave application or withdraw an in-flight request."""

    def get(self, request, pk: int):
        req = leave_selectors.get_leave_by_id(pk)
        if not req:
            raise NotFoundError(f"Leave application #{pk} does not exist.")
        return Response(s.LeaveRequestSerializer(req).data)

    def delete(self, request, pk: int):
        user_id = _actor_user_id(request)
        try:
            req = application_services.withdraw_leave(leave_id=pk, actor_user_id=user_id)
            return Response(s.LeaveRequestSerializer(req).data)
        except InvalidLeaveTransitionError as e:
            raise ConflictError(str(e)) from e


class LeaveCancellationView(APIView):
    """Request pre-start cancellation of an approved leave application."""

    def post(self, request, pk: int):
        user_id = _actor_user_id(request)
        serializer = s.CancellationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        remarks = serializer.validated_data.get("remarks", "")

        try:
            req = application_services.cancel_approved_leave(
                leave_id=pk,
                actor_user_id=user_id,
                remarks=remarks,
            )
            return Response(s.LeaveRequestSerializer(req).data)
        except InvalidLeaveTransitionError as e:
            raise ConflictError(str(e)) from e


class LeaveResumptionView(APIView):
    """Record confirmation of duty resumption following leave completion."""

    def post(self, request, pk: int):
        user_id = _actor_user_id(request)
        serializer = s.ResumptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            req = application_services.resume_duty(
                leave_id=pk,
                actor_user_id=user_id,
                actual_resumption_date=data["actual_resumption_date"],
                remarks=data.get("remarks", ""),
            )
            return Response(s.LeaveRequestSerializer(req).data)
        except InvalidLeaveTransitionError as e:
            raise ConflictError(str(e)) from e


class MyBalancesView(APIView):
    """View category leave balances and ledger transactions for caller in a given year."""

    def get(self, request):
        user_id = _actor_user_id(request)
        year_param = request.query_params.get("year")
        year = int(year_param) if year_param and year_param.isdigit() else date.today().year

        balances = list(balance_selectors.get_user_balances(user_id=user_id, year=year))
        if not balances:
            # Seed default balances on demand
            balances = balance_services.seed_default_balances(user_id=user_id, year=year)

        serializer = s.LeaveBalanceSerializer(balances, many=True)
        return Response(serializer.data)


class SubstituteQueueView(APIView):
    """Queue of leave applications awaiting this substitute's response."""

    def get(self, request):
        user_id = _actor_user_id(request)
        qs = leave_selectors.pending_substitute_requests(user_id)
        return Response(s.LeaveRequestSerializer(qs, many=True).data)

    def post(self, request, pk: int):
        user_id = _actor_user_id(request)
        serializer = s.SubstituteResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            req = workflow_services.respond_as_substitute(
                leave_id=pk,
                substitute_user_id=user_id,
                accepted=data["accepted"],
                remarks=data.get("remarks", ""),
            )
            return Response(s.LeaveRequestSerializer(req).data)
        except InvalidLeaveTransitionError as e:
            raise ConflictError(str(e)) from e


class UnitHeadReviewView(APIView):
    """Queue and decision endpoint for Unit Head reviews."""

    def get(self, request):
        user_id = _actor_user_id(request)
        # Unit Head sees requests assigned to them, or all pending reviews in dev
        qs = leave_selectors.pending_unit_head_reviews(unit_head_user_id=user_id)
        if not qs.exists():
            qs = leave_selectors.pending_unit_head_reviews()
        return Response(s.LeaveRequestSerializer(qs, many=True).data)

    def post(self, request, pk: int):
        user_id = _actor_user_id(request)
        serializer = s.UnitHeadReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            req = workflow_services.review_as_unit_head(
                leave_id=pk,
                unit_head_user_id=user_id,
                recommended=data["recommended"],
                remarks=data.get("remarks", ""),
            )
            return Response(s.LeaveRequestSerializer(req).data)
        except InvalidLeaveTransitionError as e:
            raise ConflictError(str(e)) from e


class SanctionDecisionView(APIView):
    """Queue and sanction decision endpoint for Competent Authority."""

    def get(self, request):
        user_id = _actor_user_id(request)
        qs = leave_selectors.pending_sanctions(authority_user_id=user_id)
        if not qs.exists():
            qs = leave_selectors.pending_sanctions()
        return Response(s.LeaveRequestSerializer(qs, many=True).data)

    def post(self, request, pk: int):
        user_id = _actor_user_id(request)
        serializer = s.SanctionDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            req = workflow_services.sanction_leave(
                leave_id=pk,
                authority_user_id=user_id,
                approved=data["approved"],
                remarks=data.get("remarks", ""),
            )
            return Response(s.LeaveRequestSerializer(req).data)
        except InvalidLeaveTransitionError as e:
            raise ConflictError(str(e)) from e


class HolidayCalendarView(APIView):
    """Retrieve published holidays for a year."""

    def get(self, request):
        year_param = request.query_params.get("year")
        year = int(year_param) if year_param and year_param.isdigit() else date.today().year
        qs = holiday_selectors.get_holidays_for_year(year)
        return Response(s.HolidayCalendarSerializer(qs, many=True).data)
