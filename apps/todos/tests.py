from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Todo, TodoItem


class TodoApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("todoer", "todoer@example.com", "StrongPass123!")
        self.client.force_authenticate(self.user)

    def test_create_todo_item_and_complete(self):
        create_response = self.client.post(
            "/api/todos/",
            {
                "title": "오늘 보고서 작성",
                "content": "퇴근 전까지 작성",
                "priority": "URGENT",
                "deadline_at": (timezone.now() + timezone.timedelta(hours=2)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        todo = Todo.objects.get(title="오늘 보고서 작성")

        item_response = self.client.post(
            f"/api/todos/{todo.id}/items/",
            {"content": "자료 모으기", "sort_order": 1},
            format="json",
        )
        self.assertEqual(item_response.status_code, status.HTTP_201_CREATED)
        item = TodoItem.objects.get(todo=todo)

        check_response = self.client.patch(f"/api/todos/items/{item.id}/check/", {}, format="json")
        self.assertEqual(check_response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertTrue(item.is_checked)

        complete_response = self.client.patch(f"/api/todos/{todo.id}/complete/", {}, format="json")
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        todo.refresh_from_db()
        self.assertEqual(todo.status, Todo.Status.DONE)
