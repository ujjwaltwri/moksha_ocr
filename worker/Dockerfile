FROM python:3.12-slim
WORKDIR /worker
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Day 2: add paddleocr, paddlepaddle, opencv-python-headless, rapidfuzz, imagehash here.
RUN pip install --no-cache-dir "arq>=0.26" "asyncpg>=0.30" "boto3>=1.35" "pyyaml>=6"
COPY . .
CMD ["arq", "worker.WorkerSettings"]
