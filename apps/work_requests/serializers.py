"""업무요청 API의 요청/응답 serializer.

목록, 상세, 생성/수정, 단일 필드 변경, 댓글, 첨부파일 연결을 화면 요구사항에 맞는
JSON 구조로 변환합니다.
"""

from rest_framework import serializers

from .models import WorkRequest, WorkRequestComment, WorkRequestFile


class WorkRequestListSerializer(serializers.ModelSerializer):
    """업무요청 목록 화면용 serializer.

    목록에서는 긴 본문보다 요청자/담당자 이름, 상태, 우선순위, 마감일이 중요하므로
    content는 상세 serializer에서만 제공합니다.
    """

    requester_name = serializers.CharField(source="requester.username", read_only=True)
    assignee_name = serializers.CharField(source="assignee.username", read_only=True)

    class Meta:
        model = WorkRequest
        fields = [
            "id",
            "title",
            "requester",
            "requester_name",
            "assignee",
            "assignee_name",
            "status",
            "priority",
            "deadline_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["requester", "created_at", "updated_at"]


class WorkRequestDetailSerializer(WorkRequestListSerializer):
    """업무요청 상세 화면용 serializer."""

    class Meta(WorkRequestListSerializer.Meta):
        fields = WorkRequestListSerializer.Meta.fields + [
            "content",
            "completed_at",
            "approved_at",
            "rejected_reason",
        ]


class WorkRequestCreateSerializer(serializers.ModelSerializer):
    """업무요청 생성 serializer.

    requester는 로그인 사용자로 고정합니다. 담당자가 포함되어 있으면 생성과 동시에
    ASSIGNED 상태로 시작해 대시보드의 담당 업무 목록에 바로 나타납니다.
    """

    class Meta:
        model = WorkRequest
        fields = ["title", "content", "assignee", "priority", "deadline_at"]

    def create(self, validated_data):
        # 요청자는 화면에서 받지 않고 현재 로그인한 사람으로 자동 저장합니다.
        request = self.context["request"]
        if validated_data.get("assignee"):
            validated_data["status"] = WorkRequest.Status.ASSIGNED
        return WorkRequest.objects.create(requester=request.user, **validated_data)


class WorkRequestUpdateSerializer(serializers.ModelSerializer):
    """업무요청 본문/담당자/우선순위/마감일 수정 serializer."""

    class Meta:
        model = WorkRequest
        fields = ["title", "content", "assignee", "priority", "deadline_at"]


class WorkRequestStatusSerializer(serializers.ModelSerializer):
    """status 필드만 바꾸는 경량 serializer."""

    class Meta:
        model = WorkRequest
        fields = ["status"]


class WorkRequestAssigneeSerializer(serializers.ModelSerializer):
    """assignee 필드만 바꾸는 경량 serializer."""

    class Meta:
        model = WorkRequest
        fields = ["assignee"]


class WorkRequestDeadlineSerializer(serializers.ModelSerializer):
    """deadline_at 필드만 바꾸는 경량 serializer."""

    class Meta:
        model = WorkRequest
        fields = ["deadline_at"]


class WorkRequestPrioritySerializer(serializers.ModelSerializer):
    """priority 필드만 바꾸는 경량 serializer."""

    class Meta:
        model = WorkRequest
        fields = ["priority"]


class WorkRequestCompleteSerializer(serializers.Serializer):
    """완료 요청 시 담당자가 남길 수 있는 보조 메시지 serializer."""

    message = serializers.CharField(required=False, allow_blank=True)


class WorkRequestRejectSerializer(serializers.Serializer):
    """요청자가 완료 요청을 반려할 때 필요한 사유 serializer."""

    rejected_reason = serializers.CharField()


class WorkRequestCommentSerializer(serializers.ModelSerializer):
    """업무요청 댓글 serializer."""

    author_name = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = WorkRequestComment
        fields = ["id", "work_request", "author", "author_name", "content", "created_at"]
        read_only_fields = ["work_request", "author", "created_at"]


class WorkRequestFileSerializer(serializers.ModelSerializer):
    """업무요청 첨부파일 연결 serializer.

    실제 파일은 MediaFile이 보관하고, 이 serializer는 연결 정보와 다운로드 URL을
    화면에 제공합니다.
    """

    original_name = serializers.CharField(source="media_file.original_name", read_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = WorkRequestFile
        fields = ["id", "work_request", "media_file", "original_name", "download_url", "uploaded_by", "created_at"]
        read_only_fields = ["work_request", "uploaded_by", "created_at"]

    def get_download_url(self, obj):
        """프론트가 바로 사용할 수 있는 다운로드 API 경로를 생성합니다."""
        request = self.context.get("request")
        url = f"/api/media/files/{obj.media_file_id}/download/"
        return request.build_absolute_uri(url) if request else url
