ARG PYTHON_VERSION=3.12.8-r1
ARG POSTGRESQL_VERSION=17.2-r0
ARG BUILD_BASE_VERSION=0.5-r3
ARG PY3_PIP_VERSION=24.3.1-r0

FROM alpine:3.21 AS base

ARG PYTHON_VERSION
ARG POSTGRESQL_VERSION
ARG UNIT_VERSION=1.34.0-r0
ARG TINI_VERSION=0.19.0-r3
ARG TZDATA_VERSION=2024b-r1
ARG MUSL_LOCALES_VERSION=0.1.0-r1
ARG CURL_VERSION=8.11.1-r0

RUN apk add --no-cache "tini=${TINI_VERSION}" "tzdata=${TZDATA_VERSION}" "musl-locales=${MUSL_LOCALES_VERSION}" "python3=${PYTHON_VERSION}" "unit=${UNIT_VERSION}" "unit-python3=${UNIT_VERSION}" "postgresql17-client=${POSTGRESQL_VERSION}" "curl=${CURL_VERSION}" \
    && adduser -S -D -H worker

# needs to contain url-part /static
ENV STATIC_ROOT=/opt/static/static

FROM base AS build_contrib

COPY ./contrib/prepare_db.sh /prepare_db.sh
COPY ./contrib/start_unit.sh /start_unit.sh
COPY ./contrib/healthcheck.sh /healthcheck.sh
COPY ./contrib/housekeeping.sh /housekeeping.sh

RUN chmod 555 /prepare_db.sh /start_unit.sh /healthcheck.sh /housekeeping.sh && \
    chown root:root /prepare_db.sh /start_unit.sh /healthcheck.sh /housekeeping.sh

FROM base AS build_venv

ARG PYTHON_VERSION
ARG POSTGRESQL_VERSION
ARG BUILD_BASE_VERSION
ARG PY3_PIP_VERSION

RUN apk add --no-cache "build-base=${BUILD_BASE_VERSION}" "libpq-dev=${POSTGRESQL_VERSION}" "python3-dev=${PYTHON_VERSION}" "py3-pip=${PY3_PIP_VERSION}" && \
    python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /opt/app
COPY ./manage.py /opt/app/manage.py
COPY ./kantine /opt/app/kantine
COPY ./login_hermine /opt/app/login_hermine
COPY ./abfrage /opt/app/abfrage
COPY ./unterweisung /opt/app/unterweisung

RUN find "." -exec chown root:root '{}' +  && \
    find "." -type d -exec chmod 755 '{}' +  && \
    find "." -type f -exec chmod 644 '{}' +  && \
    chmod 755 "./manage.py" && \
    python3 ./manage.py collectstatic --noinput

FROM base

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/prepare_db.sh", "/start_unit.sh"]
WORKDIR /opt/app

VOLUME /tmp

ENV PORT=8080
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV APP_WSGI=kantine.wsgi

COPY --from=build_contrib /prepare_db.sh /prepare_db.sh
COPY --from=build_contrib /start_unit.sh /start_unit.sh
COPY --from=build_contrib /healthcheck.sh /healthcheck.sh
COPY --from=build_contrib /housekeeping.sh /housekeeping.sh
COPY --from=build_venv /opt/venv /opt/venv
COPY --from=build_venv /opt/app /opt/app
COPY --from=build_venv /opt/static /opt/static

HEALTHCHECK --start-period=60s --interval=10s --timeout=60s \
  CMD ["/healthcheck.sh"]

ENV PATH="/opt/venv/bin:$PATH"
USER worker
