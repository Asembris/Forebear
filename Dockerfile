# Forebear: FastAPI + embedded Relate + the prebuilt React UI (web/dist) in one small image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FOREBEAR_DB=/data/forebear.rl

WORKDIR /app

# Runtime dependencies only (pytest is a dev tool).
COPY requirements.txt .
RUN grep -v '^pytest' requirements.txt > /tmp/req.txt \
    && pip install -r /tmp/req.txt \
    && rm /tmp/req.txt

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin forebear \
    && mkdir -p /data/live \
    && chown -R forebear:forebear /data

COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/forebear-entrypoint
COPY forebear/ forebear/
COPY web/dist/ web/dist/
COPY data/forebear.rl data/reviews.json data/
COPY data/raw/ data/raw/
COPY data/audit/ data/audit/
# The app writes its live-ingest cache to data/live; keep it on the persistent volume.
RUN ln -s /data/live /app/data/live

USER forebear
VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import json,sys,urllib.request as u; r=json.load(u.urlopen('http://127.0.0.1:8765/api/health', timeout=4)); sys.exit(0 if r.get('ok') else 1)"]

STOPSIGNAL SIGTERM
ENTRYPOINT ["forebear-entrypoint"]
