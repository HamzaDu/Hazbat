# Self-contained container (app + PostgreSQL in one):
#   docker build -t hazbat .
#   docker run -e START_LOCAL_DB=1 -p 8000:8000 -v hazbat-pgdata:/var/lib/postgresql/data -v hazbat-config:/etc/hazbat hazbat
#
# External database (START_LOCAL_DB not set):
#   docker run -p 8000:8000 -v hazbat-config:/etc/hazbat hazbat
#
# Build arguments (the two versions default to latest):
#   --build-arg PYTHON_VERSION=3.13   any version uv can install
#   --build-arg POSTGRES_VERSION=17   16, 17, 18 or latest
#   --build-arg NO_2FA=1              skip the second-factor step at login
#
# Settings are read from /etc/hazbat/hazbat.ini:
#   [database]  host, port, name, admin_password, read_write_password, read_only_password
#   [app]       session_secret, base_url, gemini_api_key (optional)

FROM alpine:latest

ARG PYTHON_VERSION=latest
ARG POSTGRES_VERSION=latest

RUN if [ "$POSTGRES_VERSION" = latest ]; then \
        postgres_packages="postgresql postgresql-contrib"; \
    else \
        postgres_packages="postgresql${POSTGRES_VERSION} postgresql${POSTGRES_VERSION}-contrib"; \
    fi \
    && apk add --no-cache \
    bash git su-exec \
    build-base gfortran openblas-dev libffi-dev jpeg-dev zlib-dev \
    $postgres_packages vim

RUN apk add --no-cache ca-certificates curl bash \
    && curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_BIN_DIR=/usr/local/bin
RUN if [ "$PYTHON_VERSION" = latest ]; then \
        uv python install --default; \
    else \
        uv python install "$PYTHON_VERSION" --default; \
    fi \
    && chmod -R a+rX /opt/python

ENV PGDATA=/var/lib/postgresql/data

# Alpine's Python refuses system-wide pip installs (PEP 668); this is a single-purpose container, so override it.
# Requirements first, so this slow layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN python3 -m venv /opt/venv
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

ARG NO_2FA=
ENV NO_2FA=$NO_2FA

RUN adduser -D app
WORKDIR /app
ENV PATH="$PATH:/app/scripts"
COPY main.py HAZbot.py ./
COPY core core
COPY routers routers
COPY services services
COPY utils utils
COPY schemas schemas
COPY --chmod=755 scripts scripts
COPY templates templates
COPY static static
RUN mkdir -p uploads/cycling_data && chown -R app /app/uploads
WORKDIR /

# Set START_LOCAL_DB=1 to run PostgreSQL inside this container. Everything else is read from /etc/hazbat/hazbat.ini.
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

EXPOSE 8000
VOLUME ["/var/lib/postgresql/data", "/app/uploads", "/etc/hazbat"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
