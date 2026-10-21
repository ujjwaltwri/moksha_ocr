FROM python:3.12-slim
WORKDIR /worker
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# glib/gomp/libgl for OpenCV and onnxruntime; the OCR models ship inside the rapidocr wheel (no download at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 libgl1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
COPY worker.py .
COPY pipeline ./pipeline
COPY templates ./templates
CMD ["arq", "worker.WorkerSettings"]
