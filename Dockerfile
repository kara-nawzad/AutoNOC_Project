# Reproducible React assets; Node is not present in the runtime image.
FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12.14 AS builder
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN python -m venv .venv
COPY requirements.txt ./
RUN .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && .venv/bin/pip install -r requirements.txt

FROM python:3.12.14-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /app
COPY --from=builder /app/.venv .venv/
COPY autonoc/ autonoc/
COPY models/ models/
COPY --from=frontend /app/autonoc/web/dist autonoc/web/dist/
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "autonoc.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
