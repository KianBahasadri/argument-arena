FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/arena.sqlite3
WORKDIR /app
COPY pyproject.toml requirements.txt ./
RUN python -m pip install --no-cache-dir --requirement requirements.txt
COPY arena ./arena
RUN groupadd --gid 10001 arena && useradd --uid 10001 --gid arena --no-create-home arena \
    && mkdir /data && chown arena:arena /data
USER 10001:10001
STOPSIGNAL SIGTERM
CMD ["python", "-m", "arena"]
