"""일정과 캘린더 API View.

일정 CRUD, 공유 참여자 관리, 참석 응답, 알림 시간 변경, 캘린더 날짜 범위 조회,
업무요청/할 일/보고서를 합친 통합 캘린더 응답을 제공합니다.
"""

from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework.views import APIView

from apps.common.responses import success_response

from .models import Schedule, ScheduleParticipant
from .serializers import (
    CalendarColorSerializer,
    CalendarMoveSerializer,
    ScheduleCreateUpdateSerializer,
    ScheduleDetailSerializer,
    ScheduleListSerializer,
    ScheduleParticipantSerializer,
    ScheduleReminderSerializer,
    ScheduleResponseSerializer,
)


class ScheduleQuerysetMixin:
    """일정 API 공통 조회/권한 믹스인.

    일정은 작성자(owner) 또는 참여자(participants__user)만 조회할 수 있습니다.
    수정/삭제/참여자 추가처럼 일정 자체를 바꾸는 작업은 owner만 허용합니다.
    """

    permission_classes = [permissions.IsAuthenticated]

    def related_queryset(self):
        """내가 만든 일정과 나에게 공유된 일정을 함께 반환합니다."""
        user = self.request.user
        return Schedule.objects.filter(Q(owner=user) | Q(participants__user=user)).distinct()

    def get_schedule(self, pk):
        """권한 범위 안에서 단건 일정을 찾습니다."""
        return generics.get_object_or_404(self.related_queryset(), pk=pk)

    def ensure_owner(self, schedule):
        """일정 작성자만 가능한 작업인지 확인합니다."""
        if schedule.owner != self.request.user:
            raise PermissionDenied("일정 작성자만 처리할 수 있습니다.")


class ScheduleListCreateView(ScheduleQuerysetMixin, generics.ListCreateAPIView):
    """일정 목록 조회와 생성 API."""

    search_fields = ["title", "content", "location"]
    ordering_fields = ["start_at", "end_at", "created_at"]

    def get_queryset(self):
        return self.related_queryset()

    def get_serializer_class(self):
        return ScheduleCreateUpdateSerializer if self.request.method == "POST" else ScheduleListSerializer


class ScheduleDetailUpdateDeleteView(ScheduleQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    """일정 상세 조회, 작성자 수정, 작성자 삭제 API."""

    def get_queryset(self):
        return self.related_queryset()

    def get_serializer_class(self):
        if self.request.method in {"PATCH", "PUT"}:
            return ScheduleCreateUpdateSerializer
        return ScheduleDetailSerializer

    def perform_update(self, serializer):
        self.ensure_owner(self.get_object())
        serializer.save()

    def perform_destroy(self, instance):
        self.ensure_owner(instance)
        instance.delete()


class ScheduleParticipantListCreateView(ScheduleQuerysetMixin, generics.ListCreateAPIView):
    """일정 참여자 목록/추가 API."""

    serializer_class = ScheduleParticipantSerializer

    def get_queryset(self):
        schedule = self.get_schedule(self.kwargs["pk"])
        return ScheduleParticipant.objects.filter(schedule=schedule)

    def perform_create(self, serializer):
        schedule = self.get_schedule(self.kwargs["pk"])
        self.ensure_owner(schedule)
        # 참여자를 추가하는 순간 공유 일정으로 표시합니다.
        schedule.is_shared = True
        schedule.save(update_fields=["is_shared"])
        serializer.save(schedule=schedule)


class ScheduleParticipantDeleteView(ScheduleQuerysetMixin, generics.DestroyAPIView):
    """일정 작성자가 참여자를 제거하는 API."""

    serializer_class = ScheduleParticipantSerializer
    lookup_url_kwarg = "participant_id"

    def get_queryset(self):
        return ScheduleParticipant.objects.filter(schedule__owner=self.request.user)


class ScheduleDateFilterView(ScheduleQuerysetMixin, generics.ListAPIView):
    """오늘/주간/월간 등 날짜 필터 목록 API의 공통 부모."""

    serializer_class = ScheduleListSerializer

    def get_queryset(self):
        return self.related_queryset()


class TodayScheduleListView(ScheduleDateFilterView):
    """오늘 시작하는 일정 목록."""

    def get_queryset(self):
        today = timezone.localdate()
        return super().get_queryset().filter(start_at__date=today)


class WeeklyScheduleListView(ScheduleDateFilterView):
    """이번 주 월요일부터 일요일까지의 일정 목록."""

    def get_queryset(self):
        today = timezone.localdate()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return super().get_queryset().filter(start_at__date__range=[start, end])


class MonthlyScheduleListView(ScheduleDateFilterView):
    """이번 달 일정 목록."""

    def get_queryset(self):
        today = timezone.localdate()
        return super().get_queryset().filter(start_at__year=today.year, start_at__month=today.month)


class SharedScheduleListView(ScheduleDateFilterView):
    """내가 참여자로 등록된 공유 일정 목록."""

    def get_queryset(self):
        return Schedule.objects.filter(participants__user=self.request.user).distinct()


class MyCreatedScheduleListView(ScheduleDateFilterView):
    """내가 작성한 일정 목록."""

    def get_queryset(self):
        return Schedule.objects.filter(owner=self.request.user)


class ScheduleResponseView(ScheduleQuerysetMixin, APIView):
    """참여자가 자신의 참석 응답을 저장하는 API."""

    def patch(self, request, pk):
        schedule = self.get_schedule(pk)
        participant = generics.get_object_or_404(ScheduleParticipant, schedule=schedule, user=request.user)
        serializer = ScheduleResponseSerializer(participant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(ScheduleParticipantSerializer(participant).data, "참석 응답이 저장되었습니다.")


class ScheduleReminderView(ScheduleQuerysetMixin, APIView):
    """일정 알림 시간을 수정하는 API."""

    def patch(self, request, pk):
        schedule = self.get_schedule(pk)
        serializer = ScheduleReminderSerializer(schedule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(ScheduleDetailSerializer(schedule).data, "일정 알림시간이 수정되었습니다.")


class ScheduleSearchView(ScheduleListCreateView):
    """일정 검색 API. 제목/본문/장소를 검색합니다."""

    pass


class CalendarScheduleCreateView(ScheduleListCreateView):
    """캘린더 화면에서 일정 생성 API를 같은 로직으로 재사용합니다."""

    pass


class CalendarScheduleUpdateView(ScheduleDetailUpdateDeleteView):
    """캘린더 화면에서 일정 수정 API를 같은 로직으로 재사용합니다."""

    pass


class CalendarScheduleMoveView(ScheduleQuerysetMixin, APIView):
    """캘린더 드래그 이동 후 일정 시작/종료 시간을 저장합니다."""

    def patch(self, request, pk):
        schedule = self.get_schedule(pk)
        self.ensure_owner(schedule)
        serializer = CalendarMoveSerializer(schedule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(ScheduleDetailSerializer(schedule).data, "일정 시간이 변경되었습니다.")


class CalendarScheduleColorView(ScheduleQuerysetMixin, APIView):
    """캘린더에서 선택한 일정 색상을 저장합니다."""

    def patch(self, request, pk):
        schedule = self.get_schedule(pk)
        serializer = CalendarColorSerializer(schedule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(ScheduleDetailSerializer(schedule).data, "일정 색상이 변경되었습니다.")


class RecurringScheduleCreateView(CalendarScheduleCreateView):
    """반복 일정 생성 API.

    현재는 기본 일정 생성 로직을 재사용하며, 반복 인스턴스 자동 생성은 추후 확장 지점입니다.
    """

    pass


class RecurringScheduleUpdateView(CalendarScheduleUpdateView):
    """반복 일정 수정 API."""

    pass


class RecurringScheduleDeleteView(ScheduleDetailUpdateDeleteView):
    """반복 일정 삭제 API."""

    pass


def parse_date(value, default):
    """YYYY-MM-DD 문자열을 date로 바꾸고 값이 없으면 기본값을 반환합니다."""
    if not value:
        return default
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_range_for_month(year, month):
    """연/월을 받아 해당 월의 시작일과 마지막일을 계산합니다."""
    start = datetime(year, month, 1).date()
    end = datetime(year + (month // 12), (month % 12) + 1, 1).date() - timedelta(days=1)
    return start, end


class CalendarRangeBaseView(ScheduleQuerysetMixin, APIView):
    """캘린더 날짜 범위 응답을 만드는 공통 부모."""

    def build_schedule_events(self, start_date, end_date):
        """Schedule 모델을 프론트 캘린더가 쓰는 event dict 목록으로 변환합니다."""
        schedules = self.related_queryset().filter(start_at__date__lte=end_date, end_at__date__gte=start_date)
        return [
            {
                "event_type": "SCHEDULE",
                "source_id": schedule.id,
                "title": schedule.title,
                "start_at": schedule.start_at,
                "end_at": schedule.end_at,
                "color": schedule.color,
                "url": f"/api/schedules/{schedule.id}/",
            }
            for schedule in schedules
        ]


class CalendarMonthView(CalendarRangeBaseView):
    """월간 캘린더 이벤트 조회 API."""

    def get(self, request):
        today = timezone.localdate()
        year = int(request.query_params.get("year", today.year))
        month = int(request.query_params.get("month", today.month))
        start, end = date_range_for_month(year, month)
        return success_response(self.build_schedule_events(start, end), "월간 달력 조회 성공")


class CalendarWeekView(CalendarRangeBaseView):
    """주간 캘린더 이벤트 조회 API."""

    def get(self, request):
        start = parse_date(request.query_params.get("start_date"), timezone.localdate())
        end = start + timedelta(days=6)
        return success_response(self.build_schedule_events(start, end), "주간 달력 조회 성공")


class CalendarDayView(CalendarRangeBaseView):
    """일간 캘린더 이벤트 조회 API."""

    def get(self, request):
        day = parse_date(request.query_params.get("date"), timezone.localdate())
        return success_response(self.build_schedule_events(day, day), "일간 달력 조회 성공")


class CalendarRangeView(CalendarRangeBaseView):
    """사용자가 지정한 임의 기간의 캘린더 이벤트 조회 API."""

    def get(self, request):
        today = timezone.localdate()
        start = parse_date(request.query_params.get("start_date"), today)
        end = parse_date(request.query_params.get("end_date"), today)
        if start > end:
            raise ValueError("start_date는 end_date보다 늦을 수 없습니다.")
        return success_response(self.build_schedule_events(start, end), "기간별 달력 조회 성공")


class IntegratedCalendarView(CalendarRangeBaseView):
    """일정, 업무요청, 할 일, 보고서를 한 캘린더 이벤트 목록으로 합칩니다."""

    def get(self, request):
        today = timezone.localdate()
        start = parse_date(request.query_params.get("start_date"), today - timedelta(days=30))
        end = parse_date(request.query_params.get("end_date"), today + timedelta(days=30))
        events = self.build_schedule_events(start, end)

        # 순환 import를 피하려고 통합 캘린더 안에서 필요한 모델을 지연 import합니다.
        from apps.reports.models import Report
        from apps.todos.models import Todo
        from apps.work_requests.models import WorkRequest

        for work in WorkRequest.objects.filter(
            Q(requester=request.user) | Q(assignee=request.user),
            deadline_at__date__range=[start, end],
        ):
            events.append(
                {
                    "event_type": "WORK_REQUEST",
                    "source_id": work.id,
                    "title": work.title,
                    "start_at": work.deadline_at,
                    "end_at": work.deadline_at,
                    "color": "#EA4335",
                    "url": f"/api/work-requests/{work.id}/",
                }
            )

        for todo in Todo.objects.filter(user=request.user, deadline_at__date__range=[start, end]):
            events.append(
                {
                    "event_type": "TODO",
                    "source_id": todo.id,
                    "title": todo.title,
                    "start_at": todo.deadline_at,
                    "end_at": todo.deadline_at,
                    "color": "#FBBC05",
                    "url": f"/api/todos/{todo.id}/",
                }
            )

        for report in Report.objects.filter(
            Q(writer=request.user) | Q(approver=request.user),
            report_date__range=[start, end],
        ):
            events.append(
                {
                    "event_type": "EXPENSE" if report.report_type == Report.ReportType.EXPENSE_REPORT else "REPORT",
                    "source_id": report.id,
                    "title": report.title,
                    "start_at": report.report_date,
                    "end_at": report.report_date,
                    "color": "#34A853",
                    "url": f"/api/reports/{report.id}/",
                }
            )

        return success_response(events, "통합 달력 조회 성공")


class CalendarFilterView(APIView):
    """프론트 캘린더 필터 UI에 사용할 이벤트 유형/색상 목록 API."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return success_response(
            [
                {"event_type": "SCHEDULE", "label": "일정", "color": "#4285F4"},
                {"event_type": "WORK_REQUEST", "label": "업무요청", "color": "#EA4335"},
                {"event_type": "TODO", "label": "할일", "color": "#FBBC05"},
                {"event_type": "REPORT", "label": "보고서", "color": "#34A853"},
                {"event_type": "EXPENSE", "label": "경비", "color": "#A142F4"},
            ]
        )
