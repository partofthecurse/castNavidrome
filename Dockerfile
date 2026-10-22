FROM alpine:3.22.1 AS build
LABEL maintainer="Ross Stewart <rosskouk@gmail.com>"
LABEL org.opencontainers.image.source=https://github.com/rosskouk/asknavidrome

RUN apk add python3 py3-pip build-base python3-dev libffi-dev openssl-dev

WORKDIR /opt

RUN python3 -m venv env

WORKDIR /opt/castnavidrome
COPY skill/ .

RUN source ../env/bin/activate && pip --no-cache-dir install wheel && pip --no-cache-dir install -r requirements-docker.txt


FROM alpine:3.22.1
LABEL maintainer="Ross Stewart <rosskouk@gmail.com>"
LABEL org.opencontainers.image.source=https://github.com/rosskouk/asknavidrome

RUN apk add python3

COPY --from=build /opt/env /opt/env
COPY --from=build /opt/castnavidrome/ /opt/castnavidrome/

WORKDIR /opt/castnavidrome

# Activate Python Virtual Environment
ENV PATH="/opt/env/bin:$PATH"

EXPOSE 5000

CMD ["python3", "app.py"]