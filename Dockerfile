FROM python:3.11-slim

WORKDIR /app

# Copy local packages with proper structure for hatchling
# Each package expects: pyproject.toml at root + source in a subdirectory matching packages=["<name>"]
COPY loop_library/pyproject.toml /packages/loop_library/pyproject.toml
COPY loop_library/ /packages/loop_library/loop_library/

COPY dispatch_client/pyproject.toml /packages/dispatch_client/pyproject.toml
COPY dispatch_client/ /packages/dispatch_client/dispatch_client/

COPY conductors/pyproject.toml /packages/conductors/pyproject.toml
COPY conductors/ /packages/conductors/conductors/

COPY librarian/pyproject.toml /packages/librarian/pyproject.toml
COPY librarian/ /packages/librarian/librarian/

# Remove duplicate pyproject.toml from inside package subdirectories
# (hatchling treats nested pyproject.toml as a project boundary and excludes those files)
RUN rm -f /packages/loop_library/loop_library/pyproject.toml \
          /packages/dispatch_client/dispatch_client/pyproject.toml \
          /packages/conductors/conductors/pyproject.toml \
          /packages/librarian/librarian/pyproject.toml

# Install local packages (order: deps first)
RUN pip install --no-cache-dir -v \
    /packages/loop_library \
    /packages/dispatch_client \
    /packages/conductors \
    /packages/librarian

# Verify local packages installed correctly
RUN python -c "import conductors; import loop_library; import dispatch_client; import librarian; print('All local packages imported successfully')"

# Copy server and install
COPY server/pyproject.toml .
COPY server/src/loop_symphony/ src/loop_symphony/
RUN pip install --no-cache-dir . && \
    python -c "import conductors; import loop_symphony; print('Server and all dependencies verified')"

# Create non-root user
RUN useradd --create-home appuser
USER appuser

# Railway sets PORT automatically
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn loop_symphony.main:app --host $HOST --port $PORT"]
