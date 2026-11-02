# API Gateway image. Build context = backend/ (it needs ../shared):
#   docker build -f gateway/Dockerfile -t grobook-gateway backend/
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY gateway/requirements.txt gateway/requirements.txt
RUN pip install --no-cache-dir -r gateway/requirements.txt

COPY shared/ shared/
COPY gateway/app/ gateway/app/

# `app` (gateway) lives in /srv/gateway; `shared` in /srv.
ENV PYTHONPATH=/srv
WORKDIR /srv/gateway

RUN useradd --no-create-home --uid 10001 gateway
USER gateway

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/gateway/health' % os.environ.get('PORT','8080'),timeout=2)"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
