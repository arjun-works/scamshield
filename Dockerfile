# ScamShield backend (FastAPI) for Cloud Run.
# Built from the repo root, because the service also needs docs/policies.md.

FROM python:3.12-slim

# uv installs the exact versions from backend/uv.lock.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# XGBoost needs the OpenMP runtime, which the slim image does not include.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/backend

# Dependencies first, so this layer is reused when only the code changes.
# --no-dev leaves out pytest, scikit-learn's training extras, matplotlib, Jupyter.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev

# Application code and the trained model (backend/ml/artifacts).
COPY backend/app ./app
COPY backend/agents ./agents
COPY backend/db ./db
COPY backend/ml ./ml
COPY backend/rules ./rules

# The bank policy the investigation agent cites.
COPY docs/policies.md /app/docs/policies.md

# Run as a non-root user.
RUN useradd --create-home appuser
USER appuser

ENV PATH="/app/backend/.venv/bin:$PATH" \
    POLICY_PATH=/app/docs/policies.md

# Cloud Run sets PORT (8080 by default).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
