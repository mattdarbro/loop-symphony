FROM python:3.11-slim

WORKDIR /app

# Copy local packages first (server depends on these)
COPY loop_library/ /packages/loop_library/
COPY librarian/ /packages/librarian/
COPY conductors/ /packages/conductors/
COPY dispatch_client/ /packages/dispatch_client/

# Install local packages
RUN pip install --no-cache-dir \
    /packages/loop_library \
    /packages/dispatch_client \
    /packages/conductors \
    /packages/librarian

# Copy server and install
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
