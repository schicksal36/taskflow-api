"""일정 공유와 달력 모델.

Schedule은 실제 일정 정보를 저장하고, ScheduleParticipant는 공유 일정에 초대된
사용자와 참석 응답을 저장합니다. 캘린더 API는 이 모델을 날짜 범위로 조회해 화면
이벤트 형태로 변환합니다.
"""

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class Schedule(TimeStampedModel):
    """일정 본문 모델.

    owner는 일정을 만든 사람입니다. 개인 일정은 owner만 접근하고, 공유 일정은
    ScheduleParticipant에 등록된 사용자도 조회할 수 있습니다. repeat_type과
    repeat_until은 반복 일정 확장용 필드입니다.
    """

    class ScheduleType(models.TextChoices):
        PERSONAL = "PERSONAL", "개인"
        WORK = "WORK", "업무"
        MEETING = "MEETING", "회의"
        TODO = "TODO", "할일"
        WORK_REQUEST = "WORK_REQUEST", "업무요청"

    class RepeatType(models.TextChoices):
        NONE = "NONE", "반복 없음"
        DAILY = "DAILY", "매일"
        WEEKLY = "WEEKLY", "매주"
        MONTHLY = "MONTHLY", "매월"
        YEARLY = "YEARLY", "매년"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="schedules")
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True)
    schedule_type = models.CharField(max_length=20, choices=ScheduleType.choices, default=ScheduleType.PERSONAL)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    location = models.CharField(max_length=200, blank=True)
    is_shared = models.BooleanField(default=False)
    remind_at = models.DateTimeField(null=True, blank=True)
    color = models.CharField(max_length=20, default="#4285F4")
    is_all_day = models.BooleanField(default=False)
    repeat_type = models.CharField(max_length=20, choices=RepeatType.choices, default=RepeatType.NONE)
    repeat_until = models.DateField(null=True, blank=True)
    timezone = models.CharField(max_length=60, default="Asia/Seoul")
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        # 캘린더는 시간 순서 표시가 기본이므로 start_at 기준으로 정렬합니다.
        ordering = ["start_at", "display_order"]
        # 사용자별 일정 목록과 날짜 범위 조회가 가장 빈번해 두 인덱스를 둡니다.
        indexes = [
            models.Index(fields=["owner", "start_at"]),
            models.Index(fields=["start_at", "end_at"]),
        ]

    def __str__(self):
        return self.title


class ScheduleParticipant(TimeStampedModel):
    """공유 일정 참여자와 참석 응답.

    unique_together로 같은 일정에 같은 사용자가 중복 초대되지 않게 막습니다.
    """

    class Response(models.TextChoices):
        PENDING = "PENDING", "대기"
        ACCEPTED = "ACCEPTED", "참석"
        DECLINED = "DECLINED", "불참"
        TENTATIVE = "TENTATIVE", "미정"

    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shared_schedules")
    response = models.CharField(max_length=20, choices=Response.choices, default=Response.PENDING)

    class Meta:
        unique_together = ["schedule", "user"]
