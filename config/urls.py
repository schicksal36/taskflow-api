"""TaskFlow 전체 URL 입구.

브라우저나 프론트엔드가 `/api/work-requests/`처럼 주소를 부르면,
이 파일이 "그 주소는 work_requests 앱으로 가세요"라고 길을 안내합니다.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("", RedirectView.as_view(url=settings.FRONTEND_URL, permanent=False), name="frontend"),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/users/", include("apps.users.urls")),
    path("api/work-requests/", include("apps.work_requests.urls")),
    path("api/todos/", include("apps.todos.urls")),
    path("api/schedules/", include("apps.schedules.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path("api/media/", include("apps.media_files.urls")),
    path("api/boards/", include("apps.boards.urls")),
    path("api/reports/", include("apps.reports.urls")),
    path("api/calendar/", include("apps.schedules.calendar_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
