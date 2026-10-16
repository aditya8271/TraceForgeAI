FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRACEFORGE_NPCI_AUTO_REFRESH=false

WORKDIR /srv/traceforge

COPY requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt

COPY app/__init__.py app/api.py app/persistence.py app/evidence.py app/claim_linker.py app/claim_reviewer.py app/reviewer.py app/fraud_ring.py app/graph_engine.py ./app/
COPY app/services/__init__.py app/services/gemini_investigator.py ./app/services/
COPY data/replay/replay_alerts.csv data/replay/replay_summary.json ./data/replay/
COPY data/generated/accounts.csv data/generated/transactions.csv data/generated/entity_observations.csv data/generated/ground_truth.csv ./data/generated/

RUN useradd --uid 10001 --create-home traceforge \
    && chown -R traceforge:traceforge /srv/traceforge
USER 10001:10001

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
