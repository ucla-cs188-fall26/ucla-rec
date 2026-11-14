# One file, two images:  docker build --target api .   /   docker build --target scraper .
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

FROM base AS api
RUN pip install .
ENV REC_DATABASE_URL=sqlite:////data/rec.db
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/v1/health')"
CMD ["uvicorn", "--factory", "rec_api.main:create_app_from_env", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS scraper
# libatomic1: Playwright's bundled Node will not start without it, so it must come first.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install ".[scrape]" && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*
ENV SCRAPE_EVERY_SECONDS=300
# Re-run forever; one failed pass does not stop the loop.
CMD ["sh", "-c", "while true; do rec-run --config /config/sources.json --api http://api:8000 --no-sandbox; sleep $SCRAPE_EVERY_SECONDS; done"]
