from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import WorkRequest


class WorkRequestApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.requester = User.objects.create_user("requester", "requester@example.com", "StrongPass123!")
        self.assignee = User.objects.create_user("assignee", "assignee@example.com", "StrongPass123!")

    def test_create_complete_and_approve_work_request(self):
        self.client.force_authenticate(self.requester)
        create_response = self.client.post(
            "/api/work-requests/",
            {
                "title": "견적서 정리",
                "content": "금요일까지 견적서를 정리해주세요.",
                "assignee": self.assignee.id,
                "priority": "HIGH",
                "deadline_at": (timezone.now() + timezone.timedelta(days=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        work = WorkRequest.objects.get(title="견적서 정리")
        self.assertEqual(work.status, WorkRequest.Status.ASSIGNED)

        self.client.force_authenticate(self.assignee)
        complete_response = self.client.patch(f"/api/work-requests/{work.id}/complete/", {}, format="json")
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        work.refresh_from_db()
        self.assertEqual(work.status, WorkRequest.Status.COMPLETED)

        self.client.force_authenticate(self.requester)
        approve_response = self.client.patch(f"/api/work-requests/{work.id}/approve/", {}, format="json")
        self.assertEqual(approve_response.status_code, status.HTTP_200_OK)
        work.refresh_from_db()
        self.assertEqual(work.status, WorkRequest.Status.APPROVED)
