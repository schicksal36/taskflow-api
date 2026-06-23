"""개발/사내 서버용 설정.

개발/사내 서버에서는 MySQL을 사용합니다.
`manage.py migrate --settings=config.settings.dev`는 MYSQL_DATABASE_URL에 있는
MySQL 서버에 테이블을 만듭니다.
"""

from .base import *  # noqa: F401,F403

DEBUG = env.bool("DEBUG", default=True)  # noqa: F405

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
