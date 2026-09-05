FROM python:3.11-slim

WORKDIR /app
COPY deploy/demo/demo_app.py .
ENV DEMO_LOG_DIR=/var/log/demo
CMD ["python", "demo_app.py"]
