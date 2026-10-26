FROM alpine:3.19 AS build
LABEL maintainer="Ross Stewart <rosskouk@gmail.com>"
LABEL org.opencontainers.image.source=https://github.com/rosskouk/asknavidrome

RUN apk add --no-cache python3 py3-pip build-base python3-dev libffi-dev openssl-dev

WORKDIR /opt

RUN python3 -m venv env

WORKDIR /opt/castnavidrome
COPY skill/ .

RUN source ../env/bin/activate && pip --no-cache-dir install wheel && pip --no-cache-dir install -r requirements-docker.txt


FROM alpine:3.19
LABEL maintainer="Ross Stewart <rosskouk@gmail.com>"
LABEL org.opencontainers.image.source=https://github.com/rosskouk/asknavidrome

RUN apk add --no-cache python3

COPY --from=build /opt/env /opt/env
COPY --from=build /opt/castnavidrome/ /opt/castnavidrome/

WORKDIR /opt/castnavidrome

# Activate Python Virtual Environment
ENV PATH="/opt/env/bin:$PATH"

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=5)" || exit 1

CMD ["python3", "app.py"]