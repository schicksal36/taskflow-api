from django.contrib import admin

from .models import Schedule, ScheduleParticipant


class ScheduleParticipantInline(admin.TabularInline):
    model = ScheduleParticipant
    extra = 0


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ["title", "owner", "schedule_type", "start_at", "end_at", "is_shared"]
    list_filter = ["schedule_type", "is_shared", "repeat_type"]
    search_fields = ["title", "content", "owner__username"]
    inlines = [ScheduleParticipantInline]


admin.site.register(ScheduleParticipant)
