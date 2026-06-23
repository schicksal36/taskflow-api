from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Schedule, ScheduleParticipant


class ScheduleApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("owner", "owner@example.com", "StrongPass123!")
        self.member = User.objects.create_user("member", "member@example.com", "StrongPass123!")

    def test_create_shared_schedule_and_participant_response(self):
        self.client.force_authenticate(self.owner)
        start_at = timezone.now() + timezone.timedelta(days=1)
        create_response = self.client.post(
            "/api/schedules/",
            {
                "title": "주간 회의",
                "content": "업무 진행 상황 공유",
                "schedule_type": "MEETING",
                "start_at": start_at.isoformat(),
                "end_at": (start_at + timezone.timedelta(hours=1)).isoformat(),
                "participant_ids": [self.member.id],
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        schedule = Schedule.objects.get(title="주간 회의")
        self.assertTrue(schedule.is_shared)

        self.client.force_authenticate(self.member)
        response = self.client.patch(
            f"/api/schedules/{schedule.id}/response/",
            {"response": ScheduleParticipant.Response.ACCEPTED},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        participant = ScheduleParticipant.objects.get(schedule=schedule, user=self.member)
        self.assertEqual(participant.response, ScheduleParticipant.Response.ACCEPTED)

    def test_integrated_calendar_returns_schedule_events(self):
        self.client.force_authenticate(self.owner)
        start_at = timezone.now() + timezone.timedelta(days=2)
        Schedule.objects.create(
            owner=self.owner,
            title="달력 표시 일정",
            start_at=start_at,
            end_at=start_at + timezone.timedelta(hours=1),
        )

        response = self.client.get("/api/calendar/integrated/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [event["title"] for event in response.data["data"]]
        self.assertIn("달력 표시 일정", titles)
