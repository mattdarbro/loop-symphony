FROM python:3.11-slim

WORKDIR /app

# Copy full server directory structure (hatchling needs src/loop_symphony/)
COPY server/pyproject.toml .
COPY server/src/loop_symphony/ src/loop_symphony/
RUN pip install --no-cache-dir .

# Create non-root user
RUN useradd --create-home appuser
USER appuser

# Railway sets PORT automatically
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn loop_symphony.main:app --host $HOST --port $PORT"]
