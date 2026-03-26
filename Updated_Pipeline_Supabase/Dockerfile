# Base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    OLLAMA_HOST=0.0.0.0 \
    PORT=5000 

WORKDIR /app

# Install system dependencies and ollama
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    procps \
    zstd \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://ollama.com/install.sh | OLLAMA_SKIP_START=1 sh

# Install CPU-only PyTorch manually to prevent downloading 10GB of Nvidia CUDA binary bloat
RUN pip install --no-cache-dir torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cpu

# Copy remaining requirements and install using the cpu index to prevent implicit CUDA downloads
COPY Updated_Pipeline_Supabase/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu \
    && pip uninstall -y nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nccl-cu12 nvidia-nvtx-cu12 || true \
    && echo "Aggressively stripping debug symbols from massive ML binaries to compress image..." \
    && apt-get install -y binutils \
    && find /usr/local/lib/python3.11/site-packages/ -name "*.so" -exec strip {} \; || true \
    && apt-get purge -y binutils && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Copy application files
COPY Updated_Pipeline_Supabase/ .

# Make the entrypoint executable
RUN chmod +x docker-entrypoint.sh
RUN chmod +x start.sh

# DIAGNOSTICS: Check size of the python packages and app directory
RUN echo "=== PIP PACKAGES SIZE ===" && du -sh /usr/local/lib/python*/site-packages/* | sort -rh | head -n 20 \
    && echo "=== APP SIZE ===" && du -sh /app/* | sort -rh

# Expose port
EXPOSE $PORT

# Start the application using the entrypoint script
CMD ["./docker-entrypoint.sh"]
