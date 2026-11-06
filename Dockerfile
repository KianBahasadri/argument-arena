# Multi-platform index digest; update intentionally with the Python/dependency locks.
FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS build
WORKDIR /build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 SOURCE_DATE_EPOCH=1767225600
COPY requirements-build.txt requirements.txt ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-build.txt \
    && python -m pip install --no-cache-dir --require-hashes --prefix=/install -r requirements.txt
COPY pyproject.toml README.md ./
COPY src/ src/
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir=/wheels . \
    && python -m pip install --no-cache-dir --no-deps --prefix=/install /wheels/*.whl

FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    AA_DATA_DIR=/var/lib/argument-arena AA_DISCORD_TOKEN_FILE=/run/secrets/discord-token
RUN groupadd --gid 10001 arena \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin arena \
    && mkdir -p /var/lib/argument-arena /run/secrets \
    && chown 10001:10001 /var/lib/argument-arena
COPY --from=build /install/ /usr/local/
USER 10001:10001
WORKDIR /var/lib/argument-arena
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
    CMD ["argument-arena", "healthcheck"]
ENTRYPOINT ["argument-arena"]
CMD ["run"]
