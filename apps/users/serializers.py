"""사용자/인증 API의 요청 검증과 응답 변환.

View는 HTTP 흐름을 처리하고, 이 파일의 serializer들은 입력값 검증, 비밀번호 정책,
JWT 응답 구성, 프로필 데이터 분리 저장 같은 도메인 규칙을 담당합니다.
"""

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import BiometricCredential, EmailVerificationCode, Profile

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """내 정보/로그인 응답에서 사용하는 사용자 기본 정보 serializer."""

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "is_email_verified",
            "is_active",
            "date_joined",
        ]
        read_only_fields = ["id", "is_email_verified", "is_active", "date_joined"]


class UserUpdateSerializer(serializers.ModelSerializer):
    """사용자 본인이 수정할 수 있는 계정 필드만 허용합니다."""

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone_number"]

    def validate_email(self, value):
        """이메일은 로그인 식별자로도 쓰이므로 다른 사용자와 중복될 수 없습니다."""
        user = self.instance
        if User.objects.exclude(pk=user.pk).filter(email=value).exists():
            raise serializers.ValidationError("이미 사용 중인 이메일입니다.")
        return value


class UserListSerializer(serializers.ModelSerializer):
    """담당자/승인자 선택 목록용 사용자 serializer.

    화면에서는 username보다 이름/닉네임/부서/직급이 필요하므로 profile을 읽어
    display_name, department, position을 함께 내려줍니다.
    """

    display_name = serializers.SerializerMethodField()
    department = serializers.CharField(source="profile.department", read_only=True)
    position = serializers.CharField(source="profile.position", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "display_name", "department", "position"]

    def get_display_name(self, obj):
        """실명, 닉네임, username 순서로 화면 표시 이름을 결정합니다."""
        full_name = obj.get_full_name().strip()
        if full_name:
            return full_name
        profile = getattr(obj, "profile", None)
        if profile and profile.nickname:
            return profile.nickname
        return obj.username


class ProfileSerializer(serializers.ModelSerializer):
    """명함처럼 화면에 표시되는 사용자 프로필 serializer."""

    class Meta:
        model = Profile
        fields = ["nickname", "position", "department", "bio", "profile_image"]


class RegisterSerializer(serializers.Serializer):
    """회원가입 요청 검증과 User/Profile 생성을 담당합니다.

    User 모델 필드와 Profile 모델 필드가 한 화면에 함께 입력되므로 일반
    ModelSerializer 대신 Serializer에서 데이터를 나눠 저장합니다.
    """

    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    nickname = serializers.CharField(required=False, allow_blank=True)
    department = serializers.CharField(required=False, allow_blank=True)
    position = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        """비밀번호 확인, 비밀번호 정책, username/email 중복을 한 번에 검증합니다."""
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "비밀번호가 서로 다릅니다."})
        validate_password(attrs["password"])
        if User.objects.filter(username=attrs["username"]).exists():
            raise serializers.ValidationError({"username": "이미 사용 중인 아이디입니다."})
        if User.objects.filter(email=attrs["email"]).exists():
            raise serializers.ValidationError({"email": "이미 사용 중인 이메일입니다."})
        return attrs

    def create(self, validated_data):
        """User 생성 후 signal로 만들어진 Profile에 추가 정보를 채웁니다."""
        profile_data = {
            "nickname": validated_data.pop("nickname", ""),
            "department": validated_data.pop("department", ""),
            "position": validated_data.pop("position", ""),
        }
        validated_data.pop("password_confirm")
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)
        Profile.objects.filter(user=user).update(**profile_data)
        return user


class LoginSerializer(serializers.Serializer):
    """아이디 또는 이메일 로그인 처리 serializer.

    authenticate()는 username 기반으로 동작하므로 이메일이 들어오면 먼저 username으로
    변환한 뒤 Django 인증 백엔드에 위임합니다.
    """

    identifier = serializers.CharField(help_text="아이디 또는 이메일")
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        """인증 성공 시 JWT access/refresh와 사용자 정보를 응답 데이터로 구성합니다."""
        identifier = attrs["identifier"]
        username = identifier
        if "@" in identifier:
            user = User.objects.filter(email=identifier).first()
            username = user.username if user else identifier

        user = authenticate(username=username, password=attrs["password"])
        if not user:
            raise serializers.ValidationError("아이디 또는 비밀번호가 올바르지 않습니다.")
        if not user.is_active:
            raise serializers.ValidationError("비활성화된 계정입니다.")

        refresh = RefreshToken.for_user(user)
        return {
            "user": UserSerializer(user).data,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }


class LogoutSerializer(serializers.Serializer):
    """refresh token을 blacklist에 넣어 로그아웃 처리합니다."""

    refresh = serializers.CharField()

    def save(self, **kwargs):
        token = RefreshToken(self.validated_data["refresh"])
        token.blacklist()


class EmailVerifySendSerializer(serializers.Serializer):
    """이메일 인증번호 발급 요청 serializer."""

    email = serializers.EmailField()

    def create(self, validated_data):
        return EmailVerificationCode.issue(
            validated_data["email"],
            EmailVerificationCode.Purpose.EMAIL_VERIFY,
        )


class EmailVerifyConfirmSerializer(serializers.Serializer):
    """이메일 인증번호 확인 serializer."""

    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)

    def validate(self, attrs):
        """가장 최근 코드가 존재하고, 미사용이며, 만료 전인지 확인합니다."""
        code = EmailVerificationCode.objects.filter(
            email=attrs["email"],
            code=attrs["code"],
            purpose=EmailVerificationCode.Purpose.EMAIL_VERIFY,
        ).order_by("-created_at").first()
        if not code or not code.can_use():
            raise serializers.ValidationError("인증번호가 올바르지 않거나 만료되었습니다.")
        attrs["code_obj"] = code
        return attrs

    def save(self, **kwargs):
        """코드를 사용 처리하고 같은 이메일의 사용자 계정을 인증 완료로 표시합니다."""
        code = self.validated_data["code_obj"]
        code.is_used = True
        code.save(update_fields=["is_used"])
        User.objects.filter(email=self.validated_data["email"]).update(is_email_verified=True)


class FindUsernameSerializer(serializers.Serializer):
    """이메일로 username을 찾기 위한 요청 검증 serializer."""

    email = serializers.EmailField()

    def validate_email(self, value):
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError("해당 이메일의 사용자가 없습니다.")
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    """비밀번호 재설정 코드 발급 요청 serializer."""

    email = serializers.EmailField()

    def validate_email(self, value):
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError("해당 이메일의 사용자가 없습니다.")
        return value

    def create(self, validated_data):
        return EmailVerificationCode.issue(
            validated_data["email"],
            EmailVerificationCode.Purpose.PASSWORD_RESET,
        )


class PasswordResetConfirmSerializer(serializers.Serializer):
    """비밀번호 재설정 코드 확인과 새 비밀번호 저장 serializer."""

    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        validate_password(attrs["new_password"])
        code = EmailVerificationCode.objects.filter(
            email=attrs["email"],
            code=attrs["code"],
            purpose=EmailVerificationCode.Purpose.PASSWORD_RESET,
        ).order_by("-created_at").first()
        if not code or not code.can_use():
            raise serializers.ValidationError("인증번호가 올바르지 않거나 만료되었습니다.")
        attrs["code_obj"] = code
        return attrs

    def save(self, **kwargs):
        """set_password()를 사용해 Django 비밀번호 해시 정책을 그대로 적용합니다."""
        user = User.objects.get(email=self.validated_data["email"])
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        code = self.validated_data["code_obj"]
        code.is_used = True
        code.save(update_fields=["is_used"])


class PasswordChangeSerializer(serializers.Serializer):
    """로그인 사용자의 비밀번호 변경 serializer."""

    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["old_password"]):
            raise serializers.ValidationError({"old_password": "기존 비밀번호가 올바르지 않습니다."})
        validate_password(attrs["new_password"], user)
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])


class UserRestoreSerializer(serializers.Serializer):
    """soft delete된 계정을 인증 코드로 다시 활성화하는 serializer."""

    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)

    def validate(self, attrs):
        code = EmailVerificationCode.objects.filter(
            email=attrs["email"],
            code=attrs["code"],
            purpose=EmailVerificationCode.Purpose.ACCOUNT_RESTORE,
        ).order_by("-created_at").first()
        if not code or not code.can_use():
            raise serializers.ValidationError("복구 인증번호가 올바르지 않거나 만료되었습니다.")
        attrs["code_obj"] = code
        return attrs

    def save(self, **kwargs):
        user = User.objects.get(email=self.validated_data["email"])
        user.is_active = True
        user.deleted_at = None
        user.save(update_fields=["is_active", "deleted_at"])
        code = self.validated_data["code_obj"]
        code.is_used = True
        code.save(update_fields=["is_used"])


class BiometricCredentialSerializer(serializers.ModelSerializer):
    """생체인식 설정 화면에 노출할 등록 기기 정보 serializer."""

    class Meta:
        model = BiometricCredential
        fields = ["id", "credential_id", "device_name", "transports", "sign_count", "last_used_at", "created_at"]
        read_only_fields = ["id", "credential_id", "transports", "sign_count", "last_used_at", "created_at"]


class BiometricRegisterOptionsSerializer(serializers.Serializer):
    """생체인식 등록 challenge 요청 serializer."""

    device_name = serializers.CharField(required=False, allow_blank=True, max_length=120)


class BiometricRegisterVerifySerializer(serializers.Serializer):
    """브라우저가 생성한 WebAuthn credential을 서버에 저장하기 위한 serializer."""

    challenge = serializers.CharField()
    credential_id = serializers.CharField()
    public_key = serializers.CharField(required=False, allow_blank=True)
    sign_count = serializers.IntegerField(required=False, min_value=0, default=0)
    device_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    transports = serializers.ListField(child=serializers.CharField(), required=False)


class BiometricLoginOptionsSerializer(serializers.Serializer):
    """생체인식 로그인 challenge 요청 serializer."""

    identifier = serializers.CharField()


class BiometricLoginVerifySerializer(serializers.Serializer):
    """생체인식 로그인 응답 검증 serializer."""

    challenge = serializers.CharField()
    credential_id = serializers.CharField()
    sign_count = serializers.IntegerField(required=False, min_value=0)
