"""업무요청 API View.

요청자/담당자 권한 범위에서 업무요청 CRUD, 상태 전이, 댓글, 첨부파일 연결,
알림 생성을 처리합니다.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.notifications.models import Notification
from apps.notifications.services import create_notification

from .models import WorkRequest, WorkRequestComment, WorkRequestFile
from .serializers import (
    WorkRequestAssigneeSerializer,
    WorkRequestCommentSerializer,
    WorkRequestCreateSerializer,
    WorkRequestDeadlineSerializer,
    WorkRequestDetailSerializer,
    WorkRequestFileSerializer,
    WorkRequestListSerializer,
    WorkRequestPrioritySerializer,
    WorkRequestRejectSerializer,
    WorkRequestStatusSerializer,
    WorkRequestUpdateSerializer,
)


class WorkRequestQuerysetMixin:
    """업무요청 API 공통 조회/권한 믹스인.

    업무요청은 요청자와 담당자만 볼 수 있습니다. 이 믹스인은 같은 필터와 역할 검사를
    모든 업무요청 View에서 재사용하게 해 권한 누락을 줄입니다.
    """

    permission_classes = [permissions.IsAuthenticated]

    def related_queryset(self):
        """로그인 사용자가 요청자 또는 담당자인 업무요청만 반환합니다."""
        user = self.request.user
        return WorkRequest.objects.filter(Q(requester=user) | Q(assignee=user)).distinct()

    def get_object_for_user(self, pk):
        """권한 범위 안에서만 단건 업무요청을 찾습니다."""
        return generics.get_object_or_404(self.related_queryset(), pk=pk)

    def ensure_requester(self, work_request):
        """요청자만 수행할 수 있는 수정/승인/반려/취소인지 확인합니다."""
        if work_request.requester != self.request.user:
            raise PermissionDenied("요청자만 처리할 수 있습니다.")

    def ensure_assignee(self, work_request):
        """담당자만 수행할 수 있는 완료 요청인지 확인합니다."""
        if work_request.assignee != self.request.user:
            raise PermissionDenied("담당자만 처리할 수 있습니다.")


class WorkRequestListCreateView(WorkRequestQuerysetMixin, generics.ListCreateAPIView):
    """업무요청 목록 조회와 생성 API."""

    search_fields = ["title", "content"]
    ordering_fields = ["deadline_at", "created_at", "priority"]

    def get_queryset(self):
        return self.related_queryset()

    def get_serializer_class(self):
        if self.request.method == "POST":
            return WorkRequestCreateSerializer
        return WorkRequestListSerializer

    def perform_create(self, serializer):
        work_request = serializer.save()
        if work_request.assignee:
            # 담당자가 지정된 업무는 생성 즉시 담당자에게 알림을 남깁니다.
            create_notification(
                work_request.assignee,
                Notification.Type.WORK_REQUEST,
                "새 업무요청이 도착했습니다.",
                work_request.title,
                "WORK_REQUEST",
                work_request.id,
            )


class WorkRequestDetailUpdateDeleteView(WorkRequestQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    """업무요청 상세 조회, 작성자 수정, 작성자 삭제 API."""

    def get_queryset(self):
        return self.related_queryset()

    def get_serializer_class(self):
        if self.request.method in {"PATCH", "PUT"}:
            return WorkRequestUpdateSerializer
        return WorkRequestDetailSerializer

    def perform_update(self, serializer):
        self.ensure_requester(self.get_object())
        serializer.save()

    def perform_destroy(self, instance):
        self.ensure_requester(instance)
        instance.delete()


class WorkRequestFieldUpdateView(WorkRequestQuerysetMixin, APIView):
    """단일 필드 PATCH API의 공통 부모.

    상태, 담당자, 마감일, 우선순위처럼 작은 변경은 전용 endpoint를 두면 프론트가
    부분 업데이트를 단순하게 호출할 수 있습니다.
    """

    serializer_class = None
    requester_only = False

    def patch(self, request, pk):
        work_request = self.get_object_for_user(pk)
        if self.requester_only:
            self.ensure_requester(work_request)
        serializer = self.serializer_class(work_request, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(WorkRequestDetailSerializer(work_request).data, "업무요청이 수정되었습니다.")


class WorkRequestStatusView(WorkRequestFieldUpdateView):
    """업무요청 status 단건 변경 API."""

    serializer_class = WorkRequestStatusSerializer


class WorkRequestAssigneeView(WorkRequestFieldUpdateView):
    """담당자 변경 API.

    담당자를 지정하면 업무가 실제 처리 대상으로 넘어간 것이므로 status도 ASSIGNED로
    맞춥니다.
    """

    serializer_class = WorkRequestAssigneeSerializer
    requester_only = True

    def patch(self, request, pk):
        response = super().patch(request, pk)
        work_request = self.get_object_for_user(pk)
        if work_request.assignee:
            work_request.status = WorkRequest.Status.ASSIGNED
            work_request.save(update_fields=["status"])
        return response


class WorkRequestDeadlineView(WorkRequestFieldUpdateView):
    """마감일 변경 API."""

    serializer_class = WorkRequestDeadlineSerializer
    requester_only = True


class WorkRequestPriorityView(WorkRequestFieldUpdateView):
    """우선순위 변경 API."""

    serializer_class = WorkRequestPrioritySerializer
    requester_only = True


class MyCreatedWorkRequestView(WorkRequestQuerysetMixin, generics.ListAPIView):
    """내가 요청한 업무만 조회합니다."""

    serializer_class = WorkRequestListSerializer

    def get_queryset(self):
        return WorkRequest.objects.filter(requester=self.request.user)


class MyAssignedWorkRequestView(WorkRequestQuerysetMixin, generics.ListAPIView):
    """내가 담당자인 업무만 조회합니다."""

    serializer_class = WorkRequestListSerializer

    def get_queryset(self):
        return WorkRequest.objects.filter(assignee=self.request.user)


class WorkRequestInProgressView(WorkRequestQuerysetMixin, generics.ListAPIView):
    """진행중 상태 업무만 조회합니다."""

    serializer_class = WorkRequestListSerializer

    def get_queryset(self):
        return self.related_queryset().filter(status=WorkRequest.Status.IN_PROGRESS)


class WorkRequestDueSoonView(WorkRequestQuerysetMixin, generics.ListAPIView):
    """현재 시각부터 3일 안에 마감되는 업무를 조회합니다."""

    serializer_class = WorkRequestListSerializer

    def get_queryset(self):
        now = timezone.now()
        return self.related_queryset().filter(deadline_at__gte=now, deadline_at__lte=now + timedelta(days=3))


class WorkRequestOverdueView(WorkRequestQuerysetMixin, generics.ListAPIView):
    """마감일이 지났고 완료 승인/취소되지 않은 업무를 조회합니다."""

    serializer_class = WorkRequestListSerializer

    def get_queryset(self):
        return self.related_queryset().filter(
            deadline_at__lt=timezone.now(),
        ).exclude(status__in=[WorkRequest.Status.APPROVED, WorkRequest.Status.CANCELED])


class WorkRequestCompleteView(WorkRequestQuerysetMixin, APIView):
    """담당자가 업무를 완료 요청 상태로 전환합니다."""

    def patch(self, request, pk):
        work_request = self.get_object_for_user(pk)
        self.ensure_assignee(work_request)
        work_request.status = WorkRequest.Status.COMPLETED
        work_request.completed_at = timezone.now()
        work_request.save(update_fields=["status", "completed_at"])
        create_notification(
            work_request.requester,
            Notification.Type.WORK_REQUEST,
            "업무 완료 승인 요청이 도착했습니다.",
            work_request.title,
            "WORK_REQUEST",
            work_request.id,
        )
        return success_response(WorkRequestDetailSerializer(work_request).data, "업무 완료 요청을 보냈습니다.")


class WorkRequestApproveView(WorkRequestQuerysetMixin, APIView):
    """요청자가 담당자의 완료 요청을 승인합니다."""

    def patch(self, request, pk):
        work_request = self.get_object_for_user(pk)
        self.ensure_requester(work_request)
        work_request.status = WorkRequest.Status.APPROVED
        work_request.approved_at = timezone.now()
        work_request.save(update_fields=["status", "approved_at"])
        create_notification(
            work_request.assignee,
            Notification.Type.WORK_REQUEST,
            "업무 완료가 승인되었습니다.",
            work_request.title,
            "WORK_REQUEST",
            work_request.id,
        )
        return success_response(WorkRequestDetailSerializer(work_request).data, "업무 완료를 승인했습니다.")


class WorkRequestRejectView(WorkRequestQuerysetMixin, APIView):
    """요청자가 담당자의 완료 요청을 반려하고 사유를 남깁니다."""

    def patch(self, request, pk):
        work_request = self.get_object_for_user(pk)
        self.ensure_requester(work_request)
        serializer = WorkRequestRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        work_request.status = WorkRequest.Status.REJECTED
        work_request.rejected_reason = serializer.validated_data["rejected_reason"]
        work_request.save(update_fields=["status", "rejected_reason"])
        create_notification(
            work_request.assignee,
            Notification.Type.WORK_REQUEST,
            "업무 완료가 반려되었습니다.",
            work_request.rejected_reason,
            "WORK_REQUEST",
            work_request.id,
        )
        return success_response(WorkRequestDetailSerializer(work_request).data, "업무를 반려했습니다.")


class WorkRequestCancelView(WorkRequestQuerysetMixin, APIView):
    """요청자가 업무요청을 취소합니다."""

    def patch(self, request, pk):
        work_request = self.get_object_for_user(pk)
        self.ensure_requester(work_request)
        work_request.status = WorkRequest.Status.CANCELED
        work_request.save(update_fields=["status"])
        if work_request.assignee:
            create_notification(
                work_request.assignee,
                Notification.Type.WORK_REQUEST,
                "업무요청이 취소되었습니다.",
                work_request.title,
                "WORK_REQUEST",
                work_request.id,
            )
        return success_response(WorkRequestDetailSerializer(work_request).data, "업무요청을 취소했습니다.")


class WorkRequestSearchView(WorkRequestListCreateView):
    """업무요청 검색 API.

    ListCreateView의 search_fields 설정을 그대로 사용해 제목/내용 검색을 제공합니다.
    """

    pass


class WorkRequestCommentListCreateView(WorkRequestQuerysetMixin, generics.ListCreateAPIView):
    """업무요청 댓글 목록/작성 API."""

    serializer_class = WorkRequestCommentSerializer

    def get_queryset(self):
        work_request = self.get_object_for_user(self.kwargs["pk"])
        return WorkRequestComment.objects.filter(work_request=work_request)

    def perform_create(self, serializer):
        work_request = self.get_object_for_user(self.kwargs["pk"])
        serializer.save(work_request=work_request, author=self.request.user)


class WorkRequestCommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """업무요청 댓글 단건 조회/수정/삭제 API."""

    serializer_class = WorkRequestCommentSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_url_kwarg = "comment_id"

    def get_queryset(self):
        user = self.request.user
        return WorkRequestComment.objects.filter(
            Q(work_request__requester=user) | Q(work_request__assignee=user),
        ).distinct()

    def perform_update(self, serializer):
        if self.get_object().author != self.request.user:
            raise PermissionDenied("작성자만 수정할 수 있습니다.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.author != self.request.user:
            raise PermissionDenied("작성자만 삭제할 수 있습니다.")
        instance.delete()


class WorkRequestFileListCreateView(WorkRequestQuerysetMixin, generics.ListCreateAPIView):
    """업무요청 첨부파일 목록/연결 API."""

    serializer_class = WorkRequestFileSerializer

    def get_queryset(self):
        work_request = self.get_object_for_user(self.kwargs["pk"])
        return WorkRequestFile.objects.filter(work_request=work_request)

    def perform_create(self, serializer):
        work_request = self.get_object_for_user(self.kwargs["pk"])
        serializer.save(work_request=work_request, uploaded_by=self.request.user)


class WorkRequestFileDetailView(generics.RetrieveDestroyAPIView):
    """업무요청 첨부파일 연결 조회/삭제 API."""

    serializer_class = WorkRequestFileSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_url_kwarg = "file_id"

    def get_queryset(self):
        user = self.request.user
        return WorkRequestFile.objects.filter(
            Q(work_request__requester=user) | Q(work_request__assignee=user),
        ).distinct()

    def perform_destroy(self, instance):
        if instance.uploaded_by != self.request.user and instance.work_request.requester != self.request.user:
            raise PermissionDenied("업로드한 사용자 또는 요청자만 삭제할 수 있습니다.")
        instance.delete()
