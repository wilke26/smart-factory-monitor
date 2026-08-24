FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /models /run/ml-signing/private /run/ml-signing/public \
    && chown -R app:app /models /run/ml-signing

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
ARG PROJECT_INSTALL=.
RUN pip install --upgrade pip \
    && pip install "${PROJECT_INSTALL}" \
    && python -m pip uninstall --yes pip

USER app
CMD ["smart-factory-simulator"]
