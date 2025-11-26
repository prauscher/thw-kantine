ARG PYPI_PIP_VERSION=25.3
ARG POSTGRESQL_VERSION=17.7-r0

FROM python:3.14-alpine3.22 AS base

ARG TZDATA_VERSION=2025b-r0
ARG CURL_VERSION=8.14.1-r2
ARG POSTGRESQL_VERSION

RUN apk add --no-cache "tzdata=${TZDATA_VERSION}" "postgresql17-client=${POSTGRESQL_VERSION}" "curl=${CURL_VERSION}" \
    && addgroup -g 1000 worker \
    && adduser -S -D -H -u 1000 -G worker worker

# Read by django
ENV STATIC_ROOT=/opt/static

FROM base AS build_contrib

COPY ./contrib/prepare_db.sh /prepare_db.sh
COPY ./contrib/start_webserver.sh /start_webserver.sh
COPY ./contrib/healthcheck.sh /healthcheck.sh
COPY ./contrib/housekeeping.sh /housekeeping.sh

RUN chmod 555 /prepare_db.sh /start_webserver.sh /healthcheck.sh /housekeeping.sh && \
    chown root:root /prepare_db.sh /start_webserver.sh /healthcheck.sh /housekeeping.sh

FROM base AS build_venv

ARG PYPI_PIP_VERSION
ARG POSTGRESQL_VERSION
ARG BUILD_BASE_VERSION=0.5-r3

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN apk add --no-cache "build-base=${BUILD_BASE_VERSION}" "libpq-dev=${POSTGRESQL_VERSION}" && \
    python3 -m pip install "pip==${PYPI_PIP_VERSION}" && \
    python3 -m pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /opt/app
COPY ./manage.py /opt/app/manage.py
COPY ./kantine /opt/app/kantine
COPY ./login_hermine /opt/app/login_hermine
COPY ./abfrage /opt/app/abfrage
COPY ./unterweisung /opt/app/unterweisung
COPY ./reservierung /opt/app/reservierung

RUN find "." -exec chown root:root '{}' +  && \
    find "." -type d -exec chmod 755 '{}' +  && \
    find "." -type f -exec chmod 644 '{}' +  && \
    chmod 755 "./manage.py" && \
    python3 ./manage.py collectstatic --noinput

FROM base

CMD ["/prepare_db.sh", "/start_webserver.sh"]
WORKDIR /opt/app

RUN mkdir /media; chown worker /media
VOLUME /media

ENV MEDIA_ROOT=/media
ENV PORT=8080
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV PYTHONUNBUFFERED=1

COPY --from=build_contrib /prepare_db.sh /prepare_db.sh
COPY --from=build_contrib /start_webserver.sh /start_webserver.sh
COPY --from=build_contrib /healthcheck.sh /healthcheck.sh
COPY --from=build_contrib /housekeeping.sh /housekeeping.sh
COPY --from=build_venv /opt/venv /opt/venv
COPY --from=build_venv /opt/app /opt/app
COPY --from=build_venv "${STATIC_ROOT}" "${STATIC_ROOT}"

HEALTHCHECK --start-period=60s --interval=10s --timeout=60s \
  CMD ["/healthcheck.sh"]

ENV PATH="/opt/venv/bin:$PATH"
USER worker
