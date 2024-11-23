FROM alpine:3.20.3 AS base

ENV PYTHON_VERSION=3.12.7-r0
ENV UNIT_VERSION=1.32.1-r3
ENV POSTGRESQL_VERSION=16.5-r0
ENV TINI_VERSION=0.19.0-r3
ENV TZDATA_VERSION=2024b-r0
ENV CURL_VERSION=8.11.0-r2
ENV BUILD_BASE_VERSION=0.5-r3
ENV PY3_PIP_VERSION=24.0-r2
ENV PIP_VERSION=24.3.1
ENV SETUPTOOLS_VERSION=75.6.0

RUN apk add --no-cache "tini=${TINI_VERSION}" "tzdata=${TZDATA_VERSION}" "python3=${PYTHON_VERSION}" "unit=${UNIT_VERSION}" "unit-python3=${UNIT_VERSION}" "postgresql16-client=${POSTGRESQL_VERSION}" "curl=${CURL_VERSION}" \
    && adduser -S -D -H worker

# needs to contain url-part /static
ENV STATIC_ROOT=/opt/static/static

FROM base AS build_contrib

COPY ./contrib/prepare_db.sh /prepare_db.sh
COPY ./contrib/start_unit.sh /start_unit.sh
COPY ./contrib/housekeeping.sh /housekeeping.sh

RUN chmod 555 /prepare_db.sh /start_unit.sh /housekeeping.sh && \
    chown root:root /prepare_db.sh /start_unit.sh /housekeeping.sh

FROM base AS build_venv

RUN apk add --no-cache "build-base=${BUILD_BASE_VERSION}" "libpq-dev=${POSTGRESQL_VERSION}" "python3-dev=${PYTHON_VERSION}" "py3-pip=${PY3_PIP_VERSION}" && \
    python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /opt/app
COPY ./manage.py /opt/app/manage.py
COPY ./kantine /opt/app/kantine
COPY ./abfrage /opt/app/abfrage
COPY ./unterweisung /opt/app/unterweisung
#COPY ./strichliste /opt/app/strichliste

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

COPY --from=build_contrib /prepare_db.sh /prepare_db.sh
COPY --from=build_contrib /start_unit.sh /start_unit.sh
COPY --from=build_contrib /housekeeping.sh /housekeeping.sh
COPY --from=build_venv /opt/venv /opt/venv
COPY --from=build_venv /opt/app /opt/app
COPY --from=build_venv /opt/static /opt/static

ENV PATH="/opt/venv/bin:$PATH"
USER worker
