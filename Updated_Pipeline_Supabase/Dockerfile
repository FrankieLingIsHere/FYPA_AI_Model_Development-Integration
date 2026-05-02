# Base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    OLLAMA_HOST=0.0.0.0 \
    PORT=5000 

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    procps \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch manually to prevent downloading 10GB of Nvidia CUDA binary bloat
RUN pip install --no-cache-dir torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cpu

# Copy remaining requirements and install using the cpu index to prevent implicit CUDA downloads
COPY Updated_Pipeline_Supabase/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu \
    && pip uninstall -y nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nccl-cu12 nvidia-nvtx-cu12 || true \
    && echo "Aggressively stripping debug symbols from massive ML binaries to compress image..." \
    && apt-get update && apt-get install -y binutils \
    # IMPORTANT: skip stripping shared libraries inside the google/, grpc/ and
    # chromadb/ namespace paths. Stripping protobuf/grpc binaries inside the
    # google namespace package has been observed to break namespace resolution
    # so that "from google import genai" fails at runtime with
    # "cannot import name 'genai' from 'google' (unknown location)" even when
    # google-genai installed cleanly.
    && find /usr/local/lib/python3.11/site-packages/ -name "*.so" \
         -not -path "*/google/*" \
         -not -path "*/grpc/*" \
         -not -path "*/chromadb/*" \
         -exec strip {} \; || true \
    && apt-get purge -y binutils && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    # Verify the Gemini SDK actually imports. If the namespace package was
    # disturbed for any reason (stripped binary, partial install, dependency
    # conflict), force-reinstall google-genai as a last-resort recovery so the
    # cloud NLP provider is guaranteed to be available at boot.
    && python -c "from google import genai; print('google-genai OK', genai.__name__)" \
       || pip install --no-cache-dir --force-reinstall --no-deps google-genai \
    && python -c "from google import genai; from google.genai import types; print('google-genai verified')"

# Copy application files
COPY Updated_Pipeline_Supabase/ .

# Make the entrypoint executable
RUN chmod +x docker-entrypoint.sh
RUN chmod +x start.sh

# Expose port
EXPOSE $PORT

# Start the application using the entrypoint script
CMD ["./docker-entrypoint.sh"]
