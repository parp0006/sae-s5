FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir requests beautifulsoup4
COPY bots.py .
CMD ["python", "-u", "bots.py"]
