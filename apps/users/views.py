"""사용자/인증 API View.

계정 생성, 로그인, 내 정보/프로필 관리, 이메일 코드, 비밀번호 재설정, 계정 복구,
생체인식 등록/로그인 흐름을 HTTP endpoint로 제공합니다.
"""

from datetime import timedelta
from secrets import token_urlsafe

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.responses import success_response

from .models import BiometricChallenge, BiometricCredential, EmailVerificationCode
from .serializers import (
    BiometricCredentialSerializer,
    BiometricLoginOptionsSerializer,
    BiometricLoginVerifySerializer,
    BiometricRegisterOptionsSerializer,
    BiometricRegisterVerifySerializer,
    EmailVerifyConfirmSerializer,
    EmailVerifySendSerializer,
    FindUsernameSerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileSerializer,
    RegisterSerializer,
    UserListSerializer,
    UserRestoreSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """회원가입 API.

    입력 검증과 실제 User/Profile 생성은 RegisterSerializer가 담당하고, View는
    성공 응답 형식과 HTTP 201 상태만 맞춥니다.
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return success_response(UserSerializer(user).data, "회원가입이 완료되었습니다.", status.HTTP_201_CREATED)


class UserListView(generics.ListAPIView):
    """담당자/승인자 선택에 사용하는 사용자 목록 API."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserListSerializer

    def get_queryset(self):
        """비활성 계정과 운영자 계정은 업무 배정 대상에서 제외합니다."""
        return (
            User.objects.filter(is_active=True, is_staff=False, is_superuser=False)
            .select_related("profile")
            .order_by("username")
        )


class LoginView(APIView):
    """JWT 로그인 API."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return success_response(serializer.validated_data, "로그인되었습니다.")


class LogoutView(APIView):
    """JWT 로그아웃 API.

    refresh token을 blacklist 처리해 이후 access token 재발급에 사용할 수 없게 합니다.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyInfoView(APIView):
    """내 계정 조회/수정/탈퇴 API."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return success_response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(UserSerializer(request.user).data, "내 정보가 수정되었습니다.")

    def delete(self, request):
        """탈퇴는 이력 보존을 위해 실제 삭제 대신 soft_delete()를 사용합니다."""
        request.user.soft_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyProfileView(APIView):
    """내 프로필 조회/수정 API.

    multipart 요청을 허용해 일반 텍스트 필드와 이미지 필드를 같은 serializer로
    처리할 수 있습니다.
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        return success_response(ProfileSerializer(request.user.profile).data)

    def patch(self, request):
        serializer = ProfileSerializer(request.user.profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(serializer.data, "프로필이 수정되었습니다.")


class ProfileImageUpdateView(APIView):
    """프로필 이미지만 교체하는 전용 API."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def patch(self, request):
        serializer = ProfileSerializer(
            request.user.profile,
            data={"profile_image": request.data.get("profile_image")},
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(serializer.data, "프로필 이미지가 수정되었습니다.")


class EmailVerifySendView(APIView):
    """이메일 인증번호 발급 API.

    현재 개발 흐름에서는 dev_code를 응답에 포함합니다. 실제 운영에서는 이 값을
    응답에서 제거하고 이메일 발송 작업으로 넘기는 방식으로 바꾸면 됩니다.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = EmailVerifySendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.save()
        return success_response({"dev_code": code.code}, "이메일 인증번호가 발급되었습니다.", status.HTTP_201_CREATED)


class EmailVerifyConfirmView(APIView):
    """이메일 인증번호 확인 API."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = EmailVerifyConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message="이메일 인증이 완료되었습니다.")


class FindUsernameView(APIView):
    """이메일 기준 username 조회 API."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = FindUsernameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        users = User.objects.filter(email=serializer.validated_data["email"])
        return success_response({"usernames": [user.username for user in users]})


class PasswordResetRequestView(APIView):
    """비밀번호 재설정 코드 발급 API."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.save()
        return success_response({"dev_code": code.code}, "비밀번호 재설정 인증번호가 발급되었습니다.", status.HTTP_201_CREATED)


class PasswordResetConfirmView(APIView):
    """재설정 코드 확인 후 새 비밀번호를 저장하는 API."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message="비밀번호가 재설정되었습니다.")


class PasswordChangeView(APIView):
    """로그인 사용자의 비밀번호 변경 API."""

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message="비밀번호가 변경되었습니다.")


class UserRestoreRequestView(APIView):
    """탈퇴/비활성 계정 복구 코드 발급 API."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get("email")
        if not email:
            return Response({"email": ["이 필드는 필수입니다."]}, status=status.HTTP_400_BAD_REQUEST)
        code = EmailVerificationCode.issue(email, EmailVerificationCode.Purpose.ACCOUNT_RESTORE)
        return success_response({"dev_code": code.code}, "계정 복구 인증번호가 발급되었습니다.", status.HTTP_201_CREATED)


class UserRestoreView(APIView):
    """복구 코드 확인 후 계정을 다시 활성화하는 API."""

    permission_classes = [permissions.AllowAny]

    def patch(self, request):
        serializer = UserRestoreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message="계정이 복구되었습니다.")


def issue_biometric_challenge(purpose, user=None, identifier=""):
    """WebAuthn 등록/로그인에 사용할 일회성 challenge를 발급합니다."""
    return BiometricChallenge.objects.create(
        user=user,
        identifier=identifier,
        challenge=token_urlsafe(48),
        purpose=purpose,
        expires_at=timezone.now() + timedelta(minutes=5),
    )


def get_active_challenge(challenge, purpose, user=None):
    """challenge가 목적에 맞고, 만료되지 않았고, 아직 사용되지 않았는지 확인합니다."""
    qs = BiometricChallenge.objects.filter(challenge=challenge, purpose=purpose).order_by("-created_at")
    if user:
        qs = qs.filter(user=user)
    challenge_obj = qs.first()
    if not challenge_obj or not challenge_obj.can_use():
        raise ValidationError("challenge가 올바르지 않거나 만료되었습니다.")
    return challenge_obj


def resolve_identifier(identifier):
    """아이디 또는 이메일을 활성 사용자로 변환합니다."""
    user = User.objects.filter(Q(username=identifier) | Q(email=identifier), is_active=True).first()
    if not user:
        raise NotFound("해당 사용자를 찾을 수 없습니다.")
    return user


class BiometricRegisterOptionsView(APIView):
    """생체인식 등록 1단계: 브라우저에 넘길 PublicKeyCredentialCreationOptions 생성."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = BiometricRegisterOptionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        challenge = issue_biometric_challenge(BiometricChallenge.Purpose.REGISTER, user=request.user)
        # 프론트는 이 응답을 navigator.credentials.create() 입력으로 변환합니다.
        return success_response(
            {
                "challenge": challenge.challenge,
                "rp": {"name": "TaskFlow", "id": request.get_host().split(":")[0]},
                "user": {
                    "id": str(request.user.id),
                    "name": request.user.username,
                    "displayName": request.user.get_full_name() or request.user.username,
                },
                "pubKeyCredParams": [
                    {"type": "public-key", "alg": -7},
                    {"type": "public-key", "alg": -257},
                ],
                "timeout": 60000,
                "attestation": "none",
                "authenticatorSelection": {
                    "authenticatorAttachment": "platform",
                    "userVerification": "preferred",
                },
                "device_name": serializer.validated_data.get("device_name", ""),
            },
            "생체인식 등록 옵션이 발급되었습니다.",
            status.HTTP_201_CREATED,
        )


class BiometricRegisterVerifyView(APIView):
    """생체인식 등록 2단계: 브라우저가 만든 credential을 저장합니다.

    현재 구현은 challenge 재사용 방지와 credential 저장을 담당합니다. 운영 수준의
    WebAuthn 보안을 강화하려면 이 지점에서 webauthn 라이브러리로 attestation과
    clientDataJSON/origin 검증을 추가하면 됩니다.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = BiometricRegisterVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        challenge = get_active_challenge(
            serializer.validated_data["challenge"],
            BiometricChallenge.Purpose.REGISTER,
            request.user,
        )
        credential, _ = BiometricCredential.objects.update_or_create(
            credential_id=serializer.validated_data["credential_id"],
            defaults={
                "user": request.user,
                "public_key": serializer.validated_data.get("public_key") or serializer.validated_data["credential_id"],
                "sign_count": serializer.validated_data.get("sign_count", 0),
                "device_name": serializer.validated_data.get("device_name", ""),
                "transports": serializer.validated_data.get("transports", []),
                "is_active": True,
            },
        )
        challenge.is_used = True
        # challenge는 한 번 사용하면 재사용하지 못하게 막아 replay 위험을 줄입니다.
        challenge.save(update_fields=["is_used"])
        return success_response(
            BiometricCredentialSerializer(credential).data,
            "생체인식 기기가 등록되었습니다.",
            status.HTTP_201_CREATED,
        )


class BiometricLoginOptionsView(APIView):
    """생체인식 로그인 1단계: 등록된 credential 목록과 challenge를 내려줍니다."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = BiometricLoginOptionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = resolve_identifier(serializer.validated_data["identifier"])
        credentials = BiometricCredential.objects.filter(user=user, is_active=True)
        if not credentials.exists():
            raise NotFound("등록된 생체인식 기기가 없습니다.")
        challenge = issue_biometric_challenge(
            BiometricChallenge.Purpose.LOGIN,
            user=user,
            identifier=serializer.validated_data["identifier"],
        )
        return success_response(
            {
                "challenge": challenge.challenge,
                "timeout": 60000,
                "userVerification": "preferred",
                "allowCredentials": [
                    {
                        "type": "public-key",
                        "id": credential.credential_id,
                        "transports": credential.transports,
                    }
                    for credential in credentials
                ],
            },
            "생체인식 로그인 옵션이 발급되었습니다.",
            status.HTTP_201_CREATED,
        )


class BiometricLoginVerifyView(APIView):
    """생체인식 로그인 2단계: credential과 challenge 확인 후 JWT를 발급합니다."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = BiometricLoginVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential = generics.get_object_or_404(
            BiometricCredential.objects.select_related("user"),
            credential_id=serializer.validated_data["credential_id"],
            is_active=True,
            user__is_active=True,
        )
        challenge = get_active_challenge(
            serializer.validated_data["challenge"],
            BiometricChallenge.Purpose.LOGIN,
            credential.user,
        )
        if serializer.validated_data.get("sign_count") is not None:
            # sign_count는 authenticator 사용 횟수 추적 값입니다.
            credential.sign_count = serializer.validated_data["sign_count"]
        credential.last_used_at = timezone.now()
        credential.save(update_fields=["sign_count", "last_used_at"])
        challenge.is_used = True
        challenge.save(update_fields=["is_used"])

        refresh = RefreshToken.for_user(credential.user)
        return success_response(
            {
                "user": UserSerializer(credential.user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            "생체인식 로그인되었습니다.",
        )


class BiometricCredentialListView(generics.ListAPIView):
    """내가 등록한 활성 생체인식 기기 목록 API."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BiometricCredentialSerializer

    def get_queryset(self):
        return BiometricCredential.objects.filter(user=self.request.user, is_active=True)


class BiometricCredentialDeleteView(generics.DestroyAPIView):
    """생체인식 기기 삭제 API.

    실제 row 삭제 대신 is_active=False로 내려 로그인 후보에서 제외합니다.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BiometricCredentialSerializer

    def get_queryset(self):
        return BiometricCredential.objects.filter(user=self.request.user, is_active=True)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active"])
