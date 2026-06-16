# ABS Librarian

ABS Librarian is a single-user audiobook workflow application for converting source audiobooks to clean M4B outputs and moving them through an Audiobookshelf-oriented library pipeline.

## Architecture

- **FastAPI** backend in `app/main.py` with API routes under `app/api/`.
- **Flet** desktop-first UI in `app/ui/main.py` with dark mode enabled.
- **Postgres** persistence via SQLAlchemy models and Alembic migrations.
- **Worker process** stub in `app/workers/worker.py` for resumable conversion jobs.
- Existing converter CLI remains available through `audiobook_converter.py` and now accepts `--mode cli` or `--mode agent`.

## Folder Pipeline

```text
incoming → staging → converting → ready_for_library → library
                      ↓
                    failed
                      ↓
                    staging
```

Source files are never automatically deleted. Successful conversions archive original sources to `converted_dir`; failed conversions move intact sources to `failed_dir`; deletion from the converted archive must be explicit and confirmation-based.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open the local web UI/landing page at <http://localhost:8000/>. FastAPI docs are available at <http://localhost:8000/docs>, and health checks are available at <http://localhost:8000/health>.

On first backend startup, ABS Librarian generates a random initial password, stores only its bcrypt hash in Postgres, and prints the password to logs/stdout. Change it from Settings after first login.

## Docker Setup

```bash
cp .env.example .env
# edit passwords, secret key, ABS settings, and AUDIOBOOK_DATA_ROOT
docker compose up --build
```

Compose starts `app`, `worker`, and `postgres`, mounts audiobook data at `/data`, and does not bake user-specific paths into the image.

## Audiobookshelf Configuration

Configure:

- ABS base URL
- ABS API token
- ABS library ID
- cache refresh interval

ABS cache refresh defaults to daily. If ABS is unreachable, the app warns and continues using cached Postgres metadata.

## Converter Modes

Interactive CLI mode remains the default:

```bash
python audiobook_converter.py --mode cli
```

Agent mode accepts JSON on stdin and emits JSON events on stdout:

```bash
printf '{"job_id":"demo","dry_run":true,"books":[{"book_id":"b1","metadata":{"target_bitrate":64,"target_channels":1}}]}' | python audiobook_converter.py --mode agent
```

## Metadata and Duplicates

Metadata priority is:

```text
embedded tags → metadata.yaml → ABS cached data → manual override
```

Duplicate warnings use exact ASIN matches first and title/author matches second. Duplicates warn during review but do not automatically block conversion.

## Backup and Restore Notes

Back up Postgres plus mounted data directories. Metadata backups should be stored under `metadata_backup_dir` before metadata-mutating operations.

## Development Commands

```bash
pytest
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# then open http://localhost:8000/
python -m app.ui.main
alembic upgrade head
```

## Troubleshooting

- Ensure FFmpeg/ffprobe are installed for real conversion work.
- Confirm Postgres is healthy and `ABS_LIBRARIAN_DATABASE_URL` matches compose credentials.
- ABS unreachable errors do not block conversion; refresh the cache after fixing URL/token/library ID.
