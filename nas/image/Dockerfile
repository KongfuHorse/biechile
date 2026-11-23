# biechile NAS agent: Python + headless Chromium + Chinese fonts.
# Built by GitHub Actions (.github/workflows/nas.yml) and pushed to Docker Hub.
FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.source=https://github.com/KongfuHorse/biechile

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    DATA_DIR=/data \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata fonts-noto-cjk ca-certificates \
      xvfb x11vnc novnc websockify fluxbox \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY bootstrap.py entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh && ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html
VOLUME /data
WORKDIR /app
# REMOTE_VIEW=1 also starts a browser view on port 16080 (open /vnc.html), protected by VNC_PASSWORD.
EXPOSE 16080
CMD ["/app/entrypoint.sh"]
