FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY scaler/__init__.py scaler/net.py scaler/worker.py scaler/gateway.py ./scaler/
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "scaler.worker", "--host", "0.0.0.0", "--port", "8080"]
