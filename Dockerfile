FROM python:3.13-bookworm

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends git ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

# Copy only metadata first (better cache)
COPY pyproject.toml /app/
COPY uv.lock* /app/

# Install dependencies only (no editable install)
RUN uv pip install --system \
  anthropic \
  "fastapi[standard]" \
  httpx \
  PyGithub

# Now copy your source files
COPY . /app

EXPOSE 9000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]

