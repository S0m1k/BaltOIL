FROM python:3.12-slim

WORKDIR /app

# WeasyPrint system dependencies (Pango, fonts)
# libgdk-pixbuf2.0-0 was renamed to libgdk-pixbuf-xlib-2.0-0 in Debian Trixie
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libffi8 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Allow overriding the package index at build time. Prod VPS has no egress to
# pypi.org/Fastly, so builds there pass a reachable mirror, e.g.:
#   --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY . .

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
