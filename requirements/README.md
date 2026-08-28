# Dependency lock workflow

`pyproject.toml` remains the human-maintained dependency policy. The committed lockfiles
are generated evidence for distinct installation boundaries:

- `build.lock`: wheel-building tools only;
- `runtime.lock`: MQTT, validation, and PostgreSQL runtime dependencies;
- `ml.lock`: runtime plus model signing and inference dependencies;
- `dev.lock`: development, test, audit, packaging frontend, and ML dependencies.

Install both `dev.lock` and `build.lock` for a complete local development environment;
the latter supplies the packaging backend used by `python -m build --no-isolation`.

Every resolved package is pinned exactly and carries hashes for all accepted artifacts.
Install with `--require-hashes`; do not add an unpinned package in Docker or CI.

Refresh with Python 3.12 and the repository-pinned `pip-tools` version:

```bash
python -m piptools compile --allow-unsafe --generate-hashes --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file requirements/runtime.lock pyproject.toml
python -m piptools compile --allow-unsafe --generate-hashes --strip-extras --no-emit-index-url --no-emit-trusted-host --extra ml --output-file requirements/ml.lock pyproject.toml
python -m piptools compile --allow-unsafe --generate-hashes --strip-extras --no-emit-index-url --no-emit-trusted-host --extra dev --extra ml --output-file requirements/dev.lock pyproject.toml
python -m piptools compile --allow-unsafe --generate-hashes --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file requirements/build.lock requirements/build.in
```

Set `CUSTOM_COMPILE_COMMAND` to the stable command shown in the generated headers when
refreshing all files. Review version changes and their upstream release notes, then run
the full quality, dependency-audit, image-build, and image-scan gates before committing.
The lockfiles improve reproducibility but do not replace vulnerability review.
