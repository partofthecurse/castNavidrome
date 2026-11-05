FROM python:3.14-alpine AS build
LABEL maintainer="part0"
LABEL org.opencontainers.image.source=https://github.com/partofthecurse/castnavidrome

RUN apk add --no-cache build-base libffi-dev openssl-dev

WORKDIR /opt

RUN python3 -m venv env

WORKDIR /opt/castnavidrome
COPY skill/requirements-docker.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    source ../env/bin/activate && pip install wheel && pip install -r requirements-docker.txt

COPY skill/ .
COPY docs/images/cast_navidrome_logo.jpg ./docs/images/cast_navidrome_logo.jpg


FROM python:3.14-alpine
LABEL maintainer="part0"
LABEL org.opencontainers.image.source=https://github.com/partofthecurse/castnavidrome

RUN apk add --no-cache libcrypto3

COPY --from=build /opt/env /opt/env
COPY --from=build /opt/castnavidrome/ /opt/castnavidrome/

WORKDIR /opt/castnavidrome

# Activate Python Virtual Environment
ENV PATH="/opt/env/bin:$PATH"

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=5)" || exit 1

CMD ["python3", "app.py"]