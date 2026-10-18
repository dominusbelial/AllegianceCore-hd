FROM python:3.12-slim
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install --no-cache-dir spandrel "numpy>=2,<3" "Pillow>=11,<14" \
 && apt-get update && apt-get install -y --no-install-recommends procps && rm -rf /var/lib/apt/lists/*
COPY esrgan_variant.py worker.sh /hd/
RUN chmod +x /hd/worker.sh
CMD ["/hd/worker.sh"]
