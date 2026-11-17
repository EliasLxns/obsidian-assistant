# Ein Image für API und Indexer; der Befehl kommt aus docker-compose.yml.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Erst nur die Metadaten kopieren: Abhängigkeiten landen in einer eigenen Schicht
# und werden nur neu installiert, wenn sich pyproject.toml ändert.
COPY pyproject.toml README.md ./
RUN mkdir -p src/assistant && touch src/assistant/__init__.py \
    && pip install . \
    && pip uninstall -y obsidian-assistant

COPY src ./src
RUN pip install --no-deps .

# Ohne Root-Rechte laufen; der Vault wird nur lesend eingebunden.
RUN useradd --create-home --uid 1000 assistant \
    && mkdir -p /cache && chown assistant /cache
USER assistant

EXPOSE 8080
CMD ["assistant", "serve", "--host", "0.0.0.0", "--port", "8080"]
