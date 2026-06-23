"""일정/참여자/캘린더 API의 serializer."""

from rest_framework import serializers

from .models import Schedule, ScheduleParticipant


class ScheduleParticipantSerializer(serializers.ModelSerializer):
    """일정 참여자 serializer.

    user id와 함께 username을 내려줘 프론트가 별도 사용자 조회 없이 참여자 목록을
    표시할 수 있게 합니다.
    """

    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = ScheduleParticipant
        fields = ["id", "schedule", "user", "username", "response", "created_at"]
        read_only_fields = ["schedule", "created_at"]


class ScheduleListSerializer(serializers.ModelSerializer):
    """일정 목록용 serializer."""

    owner_name = serializers.CharField(source="owner.username", read_only=True)
    participant_count = serializers.IntegerField(source="participants.count", read_only=True)

    class Meta:
        model = Schedule
        fields = [
            "id",
            "title",
            "owner",
            "owner_name",
            "schedule_type",
            "start_at",
            "end_at",
            "location",
            "is_shared",
            "remind_at",
            "color",
            "is_all_day",
            "repeat_type",
            "participant_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["owner", "created_at", "updated_at"]


class ScheduleDetailSerializer(ScheduleListSerializer):
    """일정 상세 serializer. 참여자 목록과 반복/표시 정보를 함께 제공합니다."""

    participants = ScheduleParticipantSerializer(many=True, read_only=True)

    class Meta(ScheduleListSerializer.Meta):
        fields = ScheduleListSerializer.Meta.fields + ["content", "repeat_until", "timezone", "display_order", "participants"]


class ScheduleCreateUpdateSerializer(serializers.ModelSerializer):
    """일정 생성/수정 serializer.

    participant_ids는 실제 Schedule 필드가 아니라 공유 대상 사용자 id 목록입니다.
    create()에서 ScheduleParticipant를 생성하고, 대상자가 있으면 is_shared를 True로
    맞춥니다.
    """

    participant_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
        help_text="일정을 공유할 사용자 id 목록",
    )

    class Meta:
        model = Schedule
        fields = [
            "title",
            "content",
            "schedule_type",
            "start_at",
            "end_at",
            "location",
            "is_shared",
            "remind_at",
            "color",
            "is_all_day",
            "repeat_type",
            "repeat_until",
            "timezone",
            "display_order",
            "participant_ids",
        ]

    def validate(self, attrs):
        """종료일시가 시작일시보다 앞서지 않게 검증합니다."""
        start_at = attrs.get("start_at", getattr(self.instance, "start_at", None))
        end_at = attrs.get("end_at", getattr(self.instance, "end_at", None))
        if start_at and end_at and start_at > end_at:
            raise serializers.ValidationError("종료일시는 시작일시보다 늦어야 합니다.")
        return attrs

    def create(self, validated_data):
        """일정 생성 후 participant_ids를 참여자 테이블로 분리 저장합니다."""
        participant_ids = validated_data.pop("participant_ids", [])
        schedule = Schedule.objects.create(owner=self.context["request"].user, **validated_data)
        for user_id in participant_ids:
            ScheduleParticipant.objects.get_or_create(schedule=schedule, user_id=user_id)
        if participant_ids:
            schedule.is_shared = True
            schedule.save(update_fields=["is_shared"])
        return schedule


class ScheduleResponseSerializer(serializers.ModelSerializer):
    """참여자의 참석 응답만 수정하는 serializer."""

    class Meta:
        model = ScheduleParticipant
        fields = ["response"]


class ScheduleReminderSerializer(serializers.ModelSerializer):
    """일정 알림 시간만 수정하는 serializer."""

    class Meta:
        model = Schedule
        fields = ["remind_at"]


class CalendarScheduleSerializer(ScheduleListSerializer):
    """캘린더 화면에서 일정 목록 형식을 재사용하기 위한 serializer."""

    pass


class CalendarMoveSerializer(serializers.ModelSerializer):
    """드래그 이동 결과로 start_at/end_at만 수정하는 serializer."""

    class Meta:
        model = Schedule
        fields = ["start_at", "end_at"]


class CalendarColorSerializer(serializers.ModelSerializer):
    """캘린더 색상만 수정하는 serializer."""

    class Meta:
        model = Schedule
        fields = ["color"]
