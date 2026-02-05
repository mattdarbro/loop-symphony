FROM python:3.11-slim

WORKDIR /app

# Copy application code and install
COPY server/pyproject.toml .
COPY server/src/ src/
RUN pip install --no-cache-dir .

# Create non-root user
RUN useradd --create-home appuser
USER appuser

# Railway sets PORT automatically
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn loop_symphony.main:app --host $HOST --port $PORT"]
