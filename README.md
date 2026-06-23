# TaskFlow API

`업무요청 사이트.xlsx` 설계서를 기준으로 만든 Django REST API입니다.
회원, 업무요청, 내 할일, 일정공유, 알림, 파일, 게시판, 보고서, 통합 달력 기능을 제공합니다.

## 설정 구분

이 프로젝트는 실무 서버용 PostgreSQL 설정과 로컬 확인용 SQLite 설정을 함께 제공합니다.

- `config.settings.dev`: 개발/사내 서버용, PostgreSQL 사용
- `config.settings.prod`: 운영 배포용, PostgreSQL 사용
- `config.settings.local`: 로컬 확인용, SQLite 사용, `testserver` 허용
- `config.settings.test`: 테스트용, 기본 PostgreSQL 테스트 DB, 옵션으로 SQLite 테스트 가능

## 실무 서버 PostgreSQL 실행

`.env` 예시:

```env
DEBUG=True
SECRET_KEY=...
ALLOWED_HOSTS=localhost,127.0.0.1,실제도메인
DATABASE_URL=postgresql://postgres:비밀번호@db:5432/taskflow_db
REDIS_URL=redis://redis:6379/0
FRONTEND_URL=http://localhost:3000
```

실행:

```powershell
cd C:\Users\schic\Programming\Django\TaskFlow\TaskFlow-api
.\.venv\Scripts\python.exe manage.py migrate --settings=config.settings.dev
.\.venv\Scripts\python.exe manage.py runserver --settings=config.settings.dev
```

운영 배포에서는:

```powershell
.\.venv\Scripts\python.exe manage.py migrate --settings=config.settings.prod
```

## 로컬 SQLite 실행

PostgreSQL/Redis가 없어도 빠르게 API를 확인하고 싶을 때 사용합니다.

```powershell
cd C:\Users\schic\Programming\Django\TaskFlow\TaskFlow-api
.\.venv\Scripts\python.exe manage.py migrate --settings=config.settings.local
.\.venv\Scripts\python.exe manage.py runserver --settings=config.settings.local
```

이 설정은 `db.local.sqlite3` 파일을 만들고, `localhost`, `127.0.0.1`, `testserver`를 허용합니다.

## 테스트 실행

PostgreSQL 테스트 DB로 실행:

```powershell
$env:DJANGO_SETTINGS_MODULE='config.settings.test'
.\.venv\Scripts\python.exe manage.py test apps.users apps.work_requests apps.todos apps.schedules apps.notifications apps.media_files apps.boards apps.reports
```

SQLite 테스트 DB로 실행:

```powershell
$env:DJANGO_SETTINGS_MODULE='config.settings.test'
$env:TASKFLOW_TEST_USE_SQLITE='true'
.\.venv\Scripts\python.exe manage.py test apps.users apps.work_requests apps.todos apps.schedules apps.notifications apps.media_files apps.boards apps.reports
```

현재 테스트는 11개이며 회원, 업무요청, 할일, 일정/달력, 알림, 파일, 게시판, 보고서 흐름을 확인합니다.

## 동작 원리

1. 사용자가 로그인하면 서버가 JWT 토큰이라는 출입증을 줍니다.
2. 프론트엔드는 API 요청마다 `Authorization: Bearer 토큰`을 보냅니다.
3. 서버는 토큰을 확인하고 그 사람이 볼 수 있는 데이터만 보여줍니다.
4. 업무요청, 할일, 일정, 게시글, 보고서는 각각 DB 테이블에 저장됩니다.
5. 상태가 바뀌면 알림이 생깁니다.
6. 통합 달력은 일정, 업무 마감, 할일 마감, 보고 날짜를 한 번에 모아 보여줍니다.

## 주요 API

- `POST /api/users/register/`: 회원가입
- `POST /api/users/login/`: 로그인
- `GET/PATCH/DELETE /api/users/me/`: 내 정보 조회, 수정, 탈퇴
- `GET/POST /api/work-requests/`: 업무요청 목록, 등록
- `PATCH /api/work-requests/<id>/complete/`: 업무 완료 요청
- `PATCH /api/work-requests/<id>/approve/`: 업무 승인
- `GET/POST /api/todos/`: 내 할일 목록, 등록
- `GET/POST /api/schedules/`: 일정 목록, 등록
- `GET /api/calendar/integrated/`: 통합 달력
- `GET /api/notifications/count/`: 안 읽은 알림 개수
- `POST /api/media/pdfs/`: PDF 업로드
- `GET/POST /api/boards/posts/`: 게시글 목록, 등록
- `GET/POST /api/reports/`: 보고서 목록, 등록

API 문서는 서버 실행 후 `http://127.0.0.1:8000/swagger-ui/`에서 볼 수 있습니다.
