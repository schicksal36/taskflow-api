from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase


class UserApiTests(APITestCase):
    """회원 API 테스트.

    테스트는 사람이 브라우저에서 버튼을 누르는 일을 코드로 대신 해보는 것입니다.
    회원가입 버튼, 로그인 버튼, 내 정보 보기 버튼을 차례대로 눌러보는 식입니다.
    """

    def test_register_login_and_me(self):
        register_response = self.client.post(
            "/api/users/register/",
            {
                "username": "worker1",
                "email": "worker1@example.com",
                "password": "StrongPass123!",
                "password_confirm": "StrongPass123!",
                "nickname": "일꾼1",
            },
            format="json",
        )
        self.assertEqual(register_response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(register_response.data["success"])

        login_response = self.client.post(
            "/api/users/login/",
            {"identifier": "worker1", "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        access = login_response.data["data"]["access"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        me_response = self.client.get("/api/users/me/")
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.data["data"]["username"], "worker1")

    def test_email_verify_flow_returns_dev_code(self):
        User = get_user_model()
        User.objects.create_user(username="mailuser", email="mailuser@example.com", password="StrongPass123!")

        send_response = self.client.post(
            "/api/users/email/verify/",
            {"email": "mailuser@example.com"},
            format="json",
        )
        self.assertEqual(send_response.status_code, status.HTTP_201_CREATED)
        code = send_response.data["data"]["dev_code"]

        confirm_response = self.client.post(
            "/api/users/email/verify/confirm/",
            {"email": "mailuser@example.com", "code": code},
            format="json",
        )
        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK)
        self.assertTrue(User.objects.get(username="mailuser").is_email_verified)
