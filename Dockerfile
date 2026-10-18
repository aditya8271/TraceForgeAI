FROM python:3.14.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TRACEFORGE_NPCI_AUTO_REFRESH=false \
    TRACEFORGE_DATA_DIR=/var/lib/traceforge/data

WORKDIR /srv/traceforge

# Install the pinned API-only dependency set. The Next.js app is deployed as a
# separate static export and is intentionally not copied into this container.
COPY requirements-api.lock ./requirements-api.lock
RUN python -m pip install --no-cache-dir -r requirements-api.lock

COPY app/__init__.py app/api.py app/persistence.py app/evidence.py app/claim_linker.py app/claim_reviewer.py app/reviewer.py app/fraud_ring.py app/graph_engine.py ./app/
COPY app/services/__init__.py app/services/gemini_investigator.py ./app/services/
COPY migrations/ ./migrations/
COPY scripts/__init__.py scripts/migrate_sqlite_to_postgres.py ./scripts/


RUN useradd --uid 10001 --create-home traceforge \
    && mkdir -p /var/lib/traceforge/data \
    && chown -R traceforge:traceforge /srv/traceforge /var/lib/traceforge

RUN chown -R traceforge:traceforge /var/lib/traceforge/data
USER 10001:10001

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8080}"]

# Include only the small replay assets required by the demo API
