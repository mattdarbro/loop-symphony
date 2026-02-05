FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY server/pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY server/src/ src/

# Create non-root user
RUN useradd --create-home appuser
USER appuser

# Railway sets PORT automatically
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn loop_symphony.main:app --host $HOST --port $PORT"]
