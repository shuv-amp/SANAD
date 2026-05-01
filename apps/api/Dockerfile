FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace

COPY apps/api /workspace/apps/api
COPY samples /workspace/samples

RUN pip install --no-cache-dir /workspace/apps/api

WORKDIR /workspace/apps/api

EXPOSE 8000

CMD ["uvicorn", "sanad_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

