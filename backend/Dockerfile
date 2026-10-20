FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Run as an unprivileged user. UID 1000 matches the default user on most
# Linux hosts so the bind mounted findings folder stays writable.
RUN useradd --uid 1000 --create-home phantom \
    && mkdir -p /srv/findings && chown phantom /srv/findings
USER phantom

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
