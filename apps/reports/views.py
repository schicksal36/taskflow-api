"""보고서/경비지출 API View.

일반 보고서와 경비지출 보고서의 CRUD, 제출/확인/보완/취소, 경비 검토/승인/반려,
경비 항목/영수증/첨부파일, PDF/Excel 생성과 다운로드를 처리합니다.
"""

from uuid import uuid4

from django.http import FileResponse, HttpResponse
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.media_files.models import AsyncTaskLog
from apps.media_files.serializers import AsyncTaskLogSerializer
from apps.notifications.models import Notification
from apps.notifications.services import create_notification

from .models import ExpenseItem, ExpenseReceipt, Report, ReportFile
from .serializers import (
    ExpenseItemSerializer,
    ExpenseReceiptSerializer,
    ReportCancelSerializer,
    ReportCreateUpdateSerializer,
    ReportDetailSerializer,
    ReportFileSerializer,
    ReportListSerializer,
    ReportReturnSerializer,
)


class ReportQuerysetMixin:
    """보고서 API에서 공통으로 사용하는 권한/조회 보조 기능.

    보고서는 작성자(writer)와 승인자(approver)만 접근할 수 있습니다. 이 믹스인은
    각 View가 같은 접근 규칙을 반복 구현하지 않도록 관련 보고서만 필터링하고,
    상태 변경 API에서 필요한 역할 검사를 제공합니다.
    """

    permission_classes = [permissions.IsAuthenticated]

    def related_queryset(self):
        """로그인 사용자가 작성자 또는 승인자인 보고서만 반환합니다."""
        user = self.request.user
        return Report.objects.filter(Q(writer=user) | Q(approver=user)).distinct()

    def get_report(self, pk):
        """권한 범위 안에서만 단건 보고서를 찾습니다.

        존재하는 보고서라도 작성자/승인자가 아니면 404처럼 보이게 처리되어
        다른 사용자의 보고서 ID를 추측하는 상황을 줄입니다.
        """
        return generics.get_object_or_404(self.related_queryset(), pk=pk)

    def ensure_writer(self, report):
        """작성자 전용 동작인지 확인합니다.

        수정, 삭제, 제출, 취소, 경비 항목 등록은 작성자의 업무 흐름에 속합니다.
        """
        if report.writer != self.request.user:
            raise PermissionDenied("작성자만 처리할 수 있습니다.")

    def ensure_approver(self, report):
        """승인자 전용 동작인지 확인합니다.

        확인완료, 보완요청, 경비 검토/승인/반려는 approver에게만 허용됩니다.
        """
        if report.approver != self.request.user:
            raise PermissionDenied("상급자/확인자만 처리할 수 있습니다.")

    def ensure_expense(self, report):
        """경비지출 보고서에서만 사용할 수 있는 API인지 확인합니다."""
        if not report.is_expense:
            raise ValidationError("경비지출 보고에서만 사용할 수 있는 기능입니다.")

    def recalculate_total(self, report):
        """경비 항목 합계를 다시 계산해 보고서 총액에 반영합니다.

        클라이언트가 total_amount를 직접 믿고 보내면 항목 합계와 어긋날 수 있으므로,
        ExpenseItem 생성/수정/삭제 뒤에는 서버가 항상 실제 항목 합계를 기준으로
        Report.total_amount를 갱신합니다.
        """
        total = report.expense_items.aggregate(total=Sum("amount"))["total"] or 0
        report.total_amount = total
        report.save(update_fields=["total_amount"])


class ReportListCreateView(ReportQuerysetMixin, generics.ListCreateAPIView):
    """보고서 목록 조회와 신규 보고서 생성을 처리합니다.

    GET은 로그인 사용자가 작성자 또는 승인자인 보고서 목록만 반환합니다.
    POST는 요청 사용자를 writer로 고정하고, 본문에 포함된 expense_items가 있으면
    보고서 생성과 함께 경비 항목도 같이 생성합니다.
    """

    search_fields = ["title", "content"]
    ordering_fields = ["report_date", "created_at", "total_amount"]

    def get_queryset(self):
        return self.related_queryset()

    def get_serializer_class(self):
        return ReportCreateUpdateSerializer if self.request.method == "POST" else ReportListSerializer


class ReportDetailUpdateDeleteView(ReportQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    """보고서 상세 조회, 수정, 삭제 API.

    수정은 작성자만 가능하고, 아직 제출 전이거나 보완/반려되어 다시 작성해야 하는
    상태에서만 허용합니다. 이미 확인/승인된 보고서는 이 API로 내용을 바꾸지 못합니다.
    """

    def get_queryset(self):
        return self.related_queryset()

    def get_serializer_class(self):
        if self.request.method in {"PATCH", "PUT"}:
            return ReportCreateUpdateSerializer
        return ReportDetailSerializer

    def perform_update(self, serializer):
        report = self.get_object()
        self.ensure_writer(report)
        if report.status not in [Report.ReportStatus.DRAFT, Report.ReportStatus.RETURNED, Report.ExpenseStatus.REJECTED]:
            raise ValidationError("현재 상태에서는 수정할 수 없습니다.")
        serializer.save()

    def perform_destroy(self, instance):
        self.ensure_writer(instance)
        instance.delete()


class ReportSubmitView(ReportQuerysetMixin, APIView):
    """작성자가 보고서를 승인자에게 제출합니다."""

    def patch(self, request, pk):
        report = self.get_report(pk)
        self.ensure_writer(report)
        # 제출 시각을 함께 저장해서 승인 대기 시간, 이력 표시, 알림 기준으로 사용합니다.
        report.status = Report.ReportStatus.SUBMITTED
        report.submitted_at = timezone.now()
        report.save(update_fields=["status", "submitted_at"])
        # 제출 이벤트는 승인자의 알림 목록과 실시간 알림 흐름에서 사용됩니다.
        create_notification(
            report.approver,
            Notification.Type.REPORT,
            "보고서가 제출되었습니다.",
            report.title,
            "REPORT",
            report.id,
        )
        return success_response(ReportDetailSerializer(report).data, "보고서를 제출했습니다.")


class ReportConfirmView(ReportQuerysetMixin, APIView):
    """승인자가 일반 보고서를 확인완료 처리합니다."""

    def patch(self, request, pk):
        report = self.get_report(pk)
        self.ensure_approver(report)
        if report.is_expense:
            raise ValidationError("경비지출은 승인 API를 사용해주세요.")
        report.status = Report.ReportStatus.CONFIRMED
        report.confirmed_at = timezone.now()
        report.save(update_fields=["status", "confirmed_at"])
        create_notification(report.writer, Notification.Type.REPORT, "보고서가 확인완료되었습니다.", report.title, "REPORT", report.id)
        return success_response(ReportDetailSerializer(report).data, "보고서를 확인완료 처리했습니다.")


class ReportReturnView(ReportQuerysetMixin, APIView):
    """승인자가 일반 보고서에 보완요청 사유를 남깁니다."""

    def patch(self, request, pk):
        report = self.get_report(pk)
        self.ensure_approver(report)
        if report.is_expense:
            raise ValidationError("경비지출은 반려 API를 사용해주세요.")
        serializer = ReportReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report.status = Report.ReportStatus.RETURNED
        report.returned_at = timezone.now()
        report.rejected_reason = serializer.validated_data["reason"]
        report.save(update_fields=["status", "returned_at", "rejected_reason"])
        create_notification(report.writer, Notification.Type.REPORT, "보고서 보완요청이 도착했습니다.", report.rejected_reason, "REPORT", report.id)
        return success_response(ReportDetailSerializer(report).data, "보완요청을 보냈습니다.")


class ExpenseReviewView(ReportQuerysetMixin, APIView):
    """경비지출 보고서를 검토중 상태로 전환합니다."""

    def patch(self, request, pk):
        report = self.get_report(pk)
        self.ensure_approver(report)
        self.ensure_expense(report)
        report.status = Report.ExpenseStatus.REVIEWING
        report.save(update_fields=["status"])
        create_notification(report.writer, Notification.Type.EXPENSE, "경비지출 보고가 검토중입니다.", report.title, "REPORT", report.id)
        return success_response(ReportDetailSerializer(report).data, "경비지출 보고를 검토중으로 변경했습니다.")


class ExpenseApproveView(ReportQuerysetMixin, APIView):
    """경비지출 보고서를 승인 처리합니다."""

    def patch(self, request, pk):
        report = self.get_report(pk)
        self.ensure_approver(report)
        self.ensure_expense(report)
        report.status = Report.ExpenseStatus.APPROVED
        report.approved_at = timezone.now()
        report.save(update_fields=["status", "approved_at"])
        create_notification(report.writer, Notification.Type.EXPENSE, "경비지출 보고가 승인되었습니다.", report.title, "REPORT", report.id)
        return success_response(ReportDetailSerializer(report).data, "경비지출 보고를 승인했습니다.")


class ExpenseRejectView(ReportQuerysetMixin, APIView):
    """경비지출 보고서를 반려하고 사유를 저장합니다."""

    def patch(self, request, pk):
        report = self.get_report(pk)
        self.ensure_approver(report)
        self.ensure_expense(report)
        serializer = ReportReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report.status = Report.ExpenseStatus.REJECTED
        report.rejected_at = timezone.now()
        report.rejected_reason = serializer.validated_data["reason"]
        report.save(update_fields=["status", "rejected_at", "rejected_reason"])
        create_notification(report.writer, Notification.Type.EXPENSE, "경비지출 보고가 반려되었습니다.", report.rejected_reason, "REPORT", report.id)
        return success_response(ReportDetailSerializer(report).data, "경비지출 보고를 반려했습니다.")


class ReportCancelView(ReportQuerysetMixin, APIView):
    """작성자가 보고서를 취소 상태로 변경합니다.

    일반 보고와 경비지출 보고는 상태 선택지가 다르므로 report_type을 기준으로
    CANCELED 값을 각각의 상태 그룹에서 선택합니다.
    """

    def patch(self, request, pk):
        report = self.get_report(pk)
        self.ensure_writer(report)
        serializer = ReportCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report.status = Report.ExpenseStatus.CANCELED if report.is_expense else Report.ReportStatus.CANCELED
        report.save(update_fields=["status"])
        return success_response(ReportDetailSerializer(report).data, "보고서를 취소했습니다.")


class MyCreatedReportView(ReportQuerysetMixin, generics.ListAPIView):
    """내가 작성한 보고서만 조회합니다."""

    serializer_class = ReportListSerializer

    def get_queryset(self):
        return Report.objects.filter(writer=self.request.user)


class MyApprovalReportView(ReportQuerysetMixin, generics.ListAPIView):
    """내가 승인자로 지정된 보고서만 조회합니다."""

    serializer_class = ReportListSerializer

    def get_queryset(self):
        return Report.objects.filter(approver=self.request.user)


class ReportTypeListView(ReportQuerysetMixin, generics.ListAPIView):
    """보고서 유형별 목록 API의 공통 부모 클래스."""

    serializer_class = ReportListSerializer
    report_type = None

    def get_queryset(self):
        return self.related_queryset().filter(report_type=self.report_type)


class DailyReportListView(ReportTypeListView):
    report_type = Report.ReportType.DAILY_REPORT


class WorkReportListView(ReportTypeListView):
    report_type = Report.ReportType.WORK_REPORT


class ExpenseReportListView(ReportTypeListView):
    report_type = Report.ReportType.EXPENSE_REPORT


class ExpenseItemListCreateView(ReportQuerysetMixin, generics.ListCreateAPIView):
    """경비지출 보고서의 경비 항목 목록/생성 API."""

    serializer_class = ExpenseItemSerializer

    def get_queryset(self):
        report = self.get_report(self.kwargs["pk"])
        self.ensure_expense(report)
        return ExpenseItem.objects.filter(report=report)

    def perform_create(self, serializer):
        report = self.get_report(self.kwargs["pk"])
        self.ensure_writer(report)
        self.ensure_expense(report)
        item = serializer.save(report=report)
        # 항목 추가 즉시 총액을 다시 계산해서 목록/상세 화면의 금액을 일관되게 유지합니다.
        self.recalculate_total(report)
        return item


class ExpenseItemDetailView(ReportQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    """경비 항목 단건 수정/삭제 API."""

    serializer_class = ExpenseItemSerializer
    lookup_url_kwarg = "item_id"

    def get_queryset(self):
        return ExpenseItem.objects.filter(report__writer=self.request.user)

    def perform_update(self, serializer):
        item = serializer.save()
        self.recalculate_total(item.report)

    def perform_destroy(self, instance):
        report = instance.report
        instance.delete()
        self.recalculate_total(report)


class ExpenseReceiptListCreateView(ReportQuerysetMixin, generics.ListCreateAPIView):
    """경비 항목에 영수증 파일을 연결합니다.

    클라이언트는 먼저 /api/media/files/로 파일을 업로드해 MediaFile ID를 얻고,
    이 API에 media_file ID를 전달합니다. 서버는 ExpenseReceipt 연결 레코드를 만들고
    대표 영수증이 비어 있으면 ExpenseItem.receipt_file에도 같은 파일을 지정합니다.
    """

    serializer_class = ExpenseReceiptSerializer

    def get_queryset(self):
        item = generics.get_object_or_404(ExpenseItem, pk=self.kwargs["item_id"], report__writer=self.request.user)
        return ExpenseReceipt.objects.filter(expense_item=item)

    def perform_create(self, serializer):
        item = generics.get_object_or_404(ExpenseItem, pk=self.kwargs["item_id"], report__writer=self.request.user)
        receipt = serializer.save(expense_item=item, uploaded_by=self.request.user)
        if not item.receipt_file_id:
            # 첫 번째 영수증은 목록에서 바로 보여줄 대표 파일로도 사용합니다.
            item.receipt_file = receipt.media_file
            item.save(update_fields=["receipt_file"])


class ExpenseReceiptDetailView(ReportQuerysetMixin, generics.RetrieveDestroyAPIView):
    """영수증 연결 정보 조회/삭제 API."""

    serializer_class = ExpenseReceiptSerializer
    lookup_url_kwarg = "receipt_id"

    def get_queryset(self):
        user = self.request.user
        return ExpenseReceipt.objects.filter(
            Q(expense_item__report__writer=user) | Q(expense_item__report__approver=user),
        ).distinct()

    def perform_destroy(self, instance):
        if instance.uploaded_by != self.request.user and instance.expense_item.report.writer != self.request.user:
            raise PermissionDenied("업로드한 사용자 또는 작성자만 삭제할 수 있습니다.")
        instance.delete()


class ExpenseReceiptDownloadView(ReportQuerysetMixin, APIView):
    """권한이 있는 사용자가 영수증 원본 파일을 다운로드합니다."""

    def get(self, request, receipt_id):
        user = request.user
        receipt = generics.get_object_or_404(
            ExpenseReceipt.objects.filter(
                Q(expense_item__report__writer=user) | Q(expense_item__report__approver=user),
            ).distinct(),
            pk=receipt_id,
        )
        media = receipt.media_file
        return FileResponse(media.file.open("rb"), as_attachment=True, filename=media.original_name)


class ReportFileListCreateView(ReportQuerysetMixin, generics.ListCreateAPIView):
    """보고서 일반 첨부파일 목록/연결 API."""

    serializer_class = ReportFileSerializer

    def get_queryset(self):
        report = self.get_report(self.kwargs["pk"])
        return ReportFile.objects.filter(report=report)

    def perform_create(self, serializer):
        report = self.get_report(self.kwargs["pk"])
        self.ensure_writer(report)
        serializer.save(report=report, uploaded_by=self.request.user)


class ReportFileDetailView(ReportQuerysetMixin, generics.RetrieveDestroyAPIView):
    """보고서 첨부파일 연결 정보 조회/삭제 API."""

    serializer_class = ReportFileSerializer
    lookup_url_kwarg = "file_id"

    def get_queryset(self):
        user = self.request.user
        return ReportFile.objects.filter(Q(report__writer=user) | Q(report__approver=user)).distinct()

    def perform_destroy(self, instance):
        if instance.uploaded_by != self.request.user and instance.report.writer != self.request.user:
            raise PermissionDenied("업로드한 사용자 또는 작성자만 삭제할 수 있습니다.")
        instance.delete()


class ReportFileDownloadView(ReportQuerysetMixin, APIView):
    """보고서 첨부파일의 실제 파일 스트림을 반환합니다."""

    def get(self, request, file_id):
        user = request.user
        report_file = generics.get_object_or_404(
            ReportFile.objects.filter(Q(report__writer=user) | Q(report__approver=user)).distinct(),
            pk=file_id,
        )
        media = report_file.media_file
        return FileResponse(media.file.open("rb"), as_attachment=True, filename=media.original_name)


class ReportAsyncGenerateView(ReportQuerysetMixin, APIView):
    """PDF/Excel 생성 요청을 비동기 작업 로그로 접수하는 공통 API.

    현재 API는 작업 ID와 PENDING 상태를 먼저 반환합니다. 실제 파일 생성은 Celery 작업이
    task_id를 기준으로 이어받는 구조를 염두에 둔 진입점입니다.
    """

    task_type = None
    message = "작업이 접수되었습니다."

    def post(self, request, pk):
        self.get_report(pk)
        task = AsyncTaskLog.objects.create(
            task_id=uuid4().hex,
            task_type=self.task_type,
            status=AsyncTaskLog.Status.PENDING,
        )
        return success_response(AsyncTaskLogSerializer(task).data, self.message, status.HTTP_202_ACCEPTED)


class ReportPdfGenerateView(ReportAsyncGenerateView):
    task_type = AsyncTaskLog.TaskType.PDF_GENERATE
    message = "보고서 PDF 생성 작업이 접수되었습니다."


class ExpenseExcelGenerateView(ReportAsyncGenerateView):
    task_type = AsyncTaskLog.TaskType.EXCEL_GENERATE
    message = "경비 Excel 생성 작업이 접수되었습니다."


class ReportPdfDownloadView(ReportQuerysetMixin, APIView):
    """보고서 내용을 즉시 PDF로 만들어 다운로드합니다.

    간단한 서버 사이드 생성 방식입니다. reportlab이 설치되어 있어야 하며, 생성된 PDF는
    디스크에 저장하지 않고 BytesIO에 만든 뒤 바로 HTTP 응답으로 내려보냅니다.
    """

    def get(self, request, pk):
        report = self.get_report(pk)
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
        except ImportError as exc:
            raise ValidationError("PDF 다운로드 라이브러리가 설치되어 있지 않습니다.") from exc

        from io import BytesIO

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        _, height = A4
        y = height - 72
        lines = [
            f"TaskFlow Report #{report.id}",
            f"Title: {report.title}",
            f"Type: {report.report_type}",
            f"Status: {report.status}",
            f"Report Date: {report.report_date}",
            f"Writer: {report.writer.username}",
            f"Approver: {report.approver.username if report.approver else '-'}",
            "",
            report.content or "",
        ]
        for line in lines:
            pdf.drawString(72, y, str(line)[:110])
            y -= 18
            if y < 72:
                # 페이지 하단에 도달하면 새 페이지를 열어 긴 본문도 잘리지 않게 합니다.
                pdf.showPage()
                y = height - 72
        pdf.save()
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="report-{report.id}.pdf"'
        return response


class ExpenseExcelDownloadView(ReportQuerysetMixin, APIView):
    """경비 항목을 Excel 파일로 즉시 생성해 다운로드합니다.

    openpyxl Workbook을 메모리에 만들고 ExpenseItem 목록을 행으로 기록한 뒤,
    .xlsx MIME 타입으로 응답합니다.
    """

    def get(self, request, pk):
        report = self.get_report(pk)
        self.ensure_expense(report)
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise ValidationError("Excel 다운로드 라이브러리가 설치되어 있지 않습니다.") from exc

        from io import BytesIO

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Expenses"
        sheet.append(["사용일", "분류", "내용", "결제수단", "금액"])
        for item in report.expense_items.all():
            sheet.append([item.expense_date, item.category, item.description, item.payment_method, item.amount])

        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="expense-{report.id}.xlsx"'
        return response


class ReportHistoryView(ReportQuerysetMixin, generics.ListAPIView):
    """보고서 이력 조회 API.

    start_date/end_date 쿼리 파라미터가 있으면 보고일 기준 기간 필터를 적용합니다.
    """

    serializer_class = ReportListSerializer

    def get_queryset(self):
        qs = self.related_queryset()
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        if start_date:
            qs = qs.filter(report_date__gte=start_date)
        if end_date:
            qs = qs.filter(report_date__lte=end_date)
        return qs
