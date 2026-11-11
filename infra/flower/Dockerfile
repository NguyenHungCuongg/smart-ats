# Celery Flower dashboard (SAD §3). Built here instead of pulling mher/flower:2.2.0 because
# that upstream image installs `redis` without `kombu[redis]`, omitting `packaging` after
# kombu 5.7.0 and crashing on startup.
FROM python:3.13.16-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1

# Include celery[redis] so kombu[redis] pulls `packaging` alongside `redis`.
RUN uv pip install --system --no-cache "flower==2.2.0" "celery[redis]~=5.6.0" && \
    groupadd -g 1000 flower && \
    useradd -u 1000 -g flower -d /data -m flower

USER flower
WORKDIR /data
EXPOSE 5555
CMD ["celery", "flower"]
