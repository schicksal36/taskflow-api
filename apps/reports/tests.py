from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import ExpenseItem, Report


class ReportApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.writer = User.objects.create_user("writer", "writer@example.com", "StrongPass123!")
        self.approver = User.objects.create_user("approver", "approver@example.com", "StrongPass123!")

    def test_submit_and_confirm_daily_report(self):
        self.client.force_authenticate(self.writer)
        create_response = self.client.post(
            "/api/reports/",
            {
                "approver": self.approver.id,
                "report_type": "DAILY_REPORT",
                "title": "일일보고",
                "content": "오늘 처리한 업무입니다.",
                "report_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        report = Report.objects.get(title="일일보고")

        submit_response = self.client.patch(f"/api/reports/{report.id}/submit/", {}, format="json")
        self.assertEqual(submit_response.status_code, status.HTTP_200_OK)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.ReportStatus.SUBMITTED)

        self.client.force_authenticate(self.approver)
        confirm_response = self.client.patch(f"/api/reports/{report.id}/confirm/", {}, format="json")
        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.ReportStatus.CONFIRMED)

    def test_expense_report_item_and_approve(self):
        self.client.force_authenticate(self.writer)
        report = Report.objects.create(
            writer=self.writer,
            approver=self.approver,
            report_type=Report.ReportType.EXPENSE_REPORT,
            title="경비지출",
            content="외근 경비",
            report_date=timezone.localdate(),
        )

        item_response = self.client.post(
            f"/api/reports/{report.id}/expenses/items/",
            {
                "expense_date": timezone.localdate().isoformat(),
                "category": "TRANSPORT",
                "description": "택시비",
                "amount": "15000.00",
                "payment_method": "CARD",
            },
            format="json",
        )
        self.assertEqual(item_response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(ExpenseItem.objects.filter(report=report).exists())

        self.client.force_authenticate(self.approver)
        approve_response = self.client.patch(f"/api/reports/{report.id}/expenses/approve/", {}, format="json")
        self.assertEqual(approve_response.status_code, status.HTTP_200_OK)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.ExpenseStatus.APPROVED)
