"""보고서/경비지출 API의 serializer.

보고서 헤더, 경비 항목, 영수증, 첨부파일의 요청 검증과 응답 구조를 정의합니다.
"""

from rest_framework import serializers

from .models import ExpenseItem, ExpenseReceipt, Report, ReportFile


class ExpenseItemSerializer(serializers.ModelSerializer):
    """경비 항목 요청/응답 serializer.

    report는 URL의 <pk>에서 서버가 결정하므로 클라이언트가 직접 넘기지 않습니다.
    receipt_file은 대표 영수증을 표시하기 위한 읽기/쓰기 가능 참조이고, 다중 영수증은
    ExpenseReceiptSerializer를 통해 별도 연결합니다.
    """

    class Meta:
        model = ExpenseItem
        fields = [
            "id",
            "report",
            "expense_date",
            "category",
            "description",
            "amount",
            "payment_method",
            "receipt_file",
            "created_at",
        ]
        read_only_fields = ["report", "created_at"]


class ExpenseReceiptSerializer(serializers.ModelSerializer):
    """경비 항목과 MediaFile을 연결하는 serializer.

    클라이언트는 media_file ID만 전달하고, expense_item과 uploaded_by는 URL과
    로그인 사용자 기준으로 서버가 채웁니다.
    """

    class Meta:
        model = ExpenseReceipt
        fields = ["id", "expense_item", "media_file", "uploaded_by", "created_at"]
        read_only_fields = ["expense_item", "uploaded_by", "created_at"]


class ReportFileSerializer(serializers.ModelSerializer):
    """보고서 일반 첨부파일 연결 serializer."""

    original_name = serializers.CharField(source="media_file.original_name", read_only=True)

    class Meta:
        model = ReportFile
        fields = ["id", "report", "media_file", "original_name", "uploaded_by", "file_category", "created_at"]
        read_only_fields = ["report", "uploaded_by", "created_at"]


class ReportListSerializer(serializers.ModelSerializer):
    """목록 화면에서 필요한 최소 보고서 정보 serializer."""

    writer_name = serializers.CharField(source="writer.username", read_only=True)
    approver_name = serializers.CharField(source="approver.username", read_only=True)

    class Meta:
        model = Report
        fields = [
            "id",
            "writer",
            "writer_name",
            "approver",
            "approver_name",
            "report_type",
            "title",
            "status",
            "report_date",
            "total_amount",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["writer", "status", "created_at", "updated_at"]


class ReportDetailSerializer(ReportListSerializer):
    """상세 화면용 serializer.

    목록 필드에 본문, 상태 변경 시각, 경비 항목, 첨부파일을 더해서 한 번의 조회로
    상세 화면을 구성할 수 있게 합니다.
    """

    expense_items = ExpenseItemSerializer(many=True, read_only=True)
    files = ReportFileSerializer(many=True, read_only=True)

    class Meta(ReportListSerializer.Meta):
        fields = ReportListSerializer.Meta.fields + [
            "content",
            "submitted_at",
            "confirmed_at",
            "returned_at",
            "approved_at",
            "rejected_at",
            "rejected_reason",
            "is_archived",
            "archived_at",
            "expense_items",
            "files",
        ]


class ReportCreateUpdateSerializer(serializers.ModelSerializer):
    """보고서 생성/수정 serializer.

    생성 시에는 request.user를 writer로 고정합니다. expense_items가 함께 들어오면
    초기 경비 항목까지 한 번에 생성하지만, 수정 시에는 보고서 헤더만 수정하고 항목은
    전용 ExpenseItem API에서 관리합니다.
    """

    expense_items = ExpenseItemSerializer(many=True, required=False)

    class Meta:
        model = Report
        fields = ["approver", "report_type", "title", "content", "report_date", "total_amount", "expense_items"]

    def create(self, validated_data):
        items = validated_data.pop("expense_items", [])
        report = Report.objects.create(writer=self.context["request"].user, **validated_data)
        for item in items:
            ExpenseItem.objects.create(report=report, **item)
        return report

    def update(self, instance, validated_data):
        validated_data.pop("expense_items", None)
        return super().update(instance, validated_data)


class ReportReturnSerializer(serializers.Serializer):
    """보완요청/반려 사유 입력 serializer."""

    reason = serializers.CharField()


class ReportCancelSerializer(serializers.Serializer):
    """취소 사유 입력 serializer.

    현재 모델에는 별도 cancel_reason 필드가 없으므로 검증 용도로만 사용합니다.
    추후 이력 테이블이 생기면 reason을 상태 변경 이력에 저장하면 됩니다.
    """

    reason = serializers.CharField(required=False, allow_blank=True)
