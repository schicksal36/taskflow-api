"""운영 배포용 설정.

운영에서는 DEBUG를 끄고, ALLOWED_HOSTS/CSRF_TRUSTED_ORIGINS/MYSQL_DATABASE_URL을
반드시 실제 서버 값으로 채워야 합니다. DB는 MySQL을 사용합니다.
"""

from .base import *  # noqa: F401,F403

DEBUG = False

MYSQL_DATABASE_URL = env("MYSQL_DATABASE_URL", default=None)  # noqa: F405
if MYSQL_DATABASE_URL:
    DATABASES = {"default": env.db_url_config(MYSQL_DATABASE_URL)}  # noqa: F405
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("MYSQL_DB"),  # noqa: F405
            "USER": env("MYSQL_USER"),  # noqa: F405
            "PASSWORD": env("MYSQL_PASSWORD"),  # noqa: F405
            "HOST": env("MYSQL_HOST", default="127.0.0.1"),  # noqa: F405
            "PORT": env("MYSQL_PORT", default="3306"),  # noqa: F405
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)  # noqa: F405

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)  # noqa: F405
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)  # noqa: F405
