"""사용자와 프로필 모델.

User는 로그인할 수 있는 사람이고, Profile은 그 사람의 명함 같은 정보입니다.
한 사람이 계정 하나와 프로필 하나를 갖도록 OneToOneField로 연결합니다.
"""

from datetime import timedelta
from random import randint

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.common.models import TimeStampedModel


class User(AbstractUser):
    """TaskFlow 로그인 계정.

    Django 기본 AbstractUser를 확장해 이메일 고유성, 전화번호, 이메일 인증 여부,
    탈퇴 시각을 추가합니다. 실제 row를 바로 삭제하지 않고 soft_delete()로 비활성화해
    업무요청/보고서 작성자 이력이 끊기지 않게 합니다.
    """

    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=30, blank=True)
    is_email_verified = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def soft_delete(self):
        """회원탈퇴는 데이터를 바로 지우지 않고 비활성화로 처리합니다."""

        self.is_active = False
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_active", "deleted_at"])


class Profile(TimeStampedModel):
    """사용자 부가 프로필.

    계정 인증에 필요한 정보(User)와 화면 표시/조직 정보(Profile)를 분리합니다.
    User 생성 직후 post_save signal이 빈 Profile을 자동 생성하므로 프론트는
    별도 프로필 생성 API를 호출하지 않아도 됩니다.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    nickname = models.CharField(max_length=50, blank=True)
    position = models.CharField(max_length=50, blank=True)
    department = models.CharField(max_length=80, blank=True)
    bio = models.TextField(blank=True)
    profile_image = models.ImageField(upload_to="profiles/%Y/%m/%d/", blank=True, null=True)

    def __str__(self):
        return self.nickname or self.user.username


class EmailVerificationCode(TimeStampedModel):
    """이메일 인증, 비밀번호 재설정, 계정 복구에 재사용되는 6자리 코드.

    purpose로 사용 목적을 구분해 같은 이메일이라도 인증 코드와 비밀번호 재설정 코드가
    섞이지 않게 합니다. can_use()는 이미 사용한 코드와 만료 코드를 막는 공통 검증입니다.
    """

    class Purpose(models.TextChoices):
        EMAIL_VERIFY = "EMAIL_VERIFY", "이메일 인증"
        PASSWORD_RESET = "PASSWORD_RESET", "비밀번호 재설정"
        ACCOUNT_RESTORE = "ACCOUNT_RESTORE", "탈퇴 복구"

    email = models.EmailField()
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    code = models.CharField(max_length=6)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()

    @classmethod
    def issue(cls, email: str, purpose: str):
        """6자리 숫자 코드를 만듭니다.

        실제 운영에서는 이 코드를 이메일로 보내면 됩니다. 개발 중에는 API 응답에
        dev_code로 보여주어 프론트엔드가 흐름을 테스트할 수 있게 했습니다.
        """

        return cls.objects.create(
            email=email,
            purpose=purpose,
            code=f"{randint(0, 999999):06d}",
            expires_at=timezone.now() + timedelta(minutes=10),
        )

    def can_use(self) -> bool:
        return not self.is_used and self.expires_at >= timezone.now()


class BiometricChallenge(TimeStampedModel):
    """WebAuthn 등록/로그인 challenge 저장소.

    생체인식은 서버가 challenge를 발급하고 브라우저가 그 challenge를 서명/응답한 뒤
    서버에 다시 제출하는 왕복 구조입니다. 이 모델은 challenge 재사용을 막기 위해
    is_used와 expires_at을 저장합니다.
    """

    class Purpose(models.TextChoices):
        REGISTER = "REGISTER", "생체인식 등록"
        LOGIN = "LOGIN", "생체인식 로그인"

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="biometric_challenges")
    identifier = models.CharField(max_length=255, blank=True)
    challenge = models.CharField(max_length=255, unique=True)
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()

    def can_use(self) -> bool:
        return not self.is_used and self.expires_at >= timezone.now()


class BiometricCredential(TimeStampedModel):
    """사용자별 등록 생체인식 credential.

    credential_id는 브라우저/OS 패스키가 돌려주는 공개 식별자입니다. public_key와
    sign_count는 WebAuthn 검증을 확장할 때 사용하는 값이며, is_active=False로 처리해
    삭제 이력을 보존하면서도 로그인에는 사용하지 않게 합니다.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="biometric_credentials")
    credential_id = models.TextField(unique=True)
    public_key = models.TextField()
    sign_count = models.BigIntegerField(default=0)
    device_name = models.CharField(max_length=120, blank=True)
    transports = models.JSONField(default=list, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return self.device_name or f"{self.user.username} credential"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """회원가입 직후 빈 프로필을 자동으로 만들어줍니다."""

    if created:
        Profile.objects.create(user=instance)
