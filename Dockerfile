FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /models && chown app:app /models

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
ARG PROJECT_INSTALL=.
RUN pip install --upgrade pip && pip install "${PROJECT_INSTALL}"

USER app
CMD ["smart-factory-simulator"]
