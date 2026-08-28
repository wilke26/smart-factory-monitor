FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS builder

ENV PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements/build.lock requirements/build.lock
RUN python -m pip install --require-hashes -r requirements/build.lock

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m build --wheel --no-isolation --outdir /dist

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
COPY requirements/runtime.lock requirements/ml.lock ./requirements/
ARG DEPENDENCY_LOCK=requirements/runtime.lock
RUN python -m pip install --require-hashes -r "${DEPENDENCY_LOCK}"

COPY --from=builder /dist/*.whl /tmp/
RUN python -m pip install --no-deps /tmp/smart_factory_monitor-*.whl \
    && rm /tmp/smart_factory_monitor-*.whl \
    && python -m pip check \
    && python -m pip uninstall --yes pip

USER app
CMD ["smart-factory-simulator"]
