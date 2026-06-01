FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache).
# Allow overriding the package index at build time. Prod VPS has no egress to
# pypi.org/Fastly, so builds there pass a reachable mirror, e.g.:
#   --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
