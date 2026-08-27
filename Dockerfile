FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /models /run/ml-signing/private /run/ml-signing/public \
        /run/audit-attestation/private /run/audit-attestation/public /audit-checkpoints \
    && chown -R app:app /models /run/ml-signing /run/audit-attestation /audit-checkpoints

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
ARG PROJECT_INSTALL=.
RUN pip install --upgrade pip \
    && pip install "${PROJECT_INSTALL}" \
    && python -m pip uninstall --yes pip

USER app
CMD ["smart-factory-simulator"]
