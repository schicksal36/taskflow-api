from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import EmailVerificationCode, Profile, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("TaskFlow 추가 정보", {"fields": ("phone_number", "is_email_verified", "deleted_at")}),
    )
    list_display = ["username", "email", "is_active", "is_email_verified", "date_joined"]
    search_fields = ["username", "email", "first_name", "last_name"]


admin.site.register(Profile)
admin.site.register(EmailVerificationCode)
