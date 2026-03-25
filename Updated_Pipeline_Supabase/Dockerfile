# Base image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    OLLAMA_HOST=0.0.0.0 \
    PORT=5000 

WORKDIR /app

# Install system dependencies and ollama
RUN apt-get update && apt-get install -y \
    curl \
    git \
    procps \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && curl -L https://ollama.com/download/ollama-linux-amd64 -o /usr/bin/ollama \
    && chmod +x /usr/bin/ollama

# Copy requirements and install Python dependencies
COPY Updated_Pipeline_Supabase/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY Updated_Pipeline_Supabase/ .

# Pre-pull required Ollama models so they are baked into the image
# This prevents downloading multi-gigabyte files during container startup
RUN bash -c "nohup ollama serve > /dev/null 2>&1 &" && sleep 5 \
    && ollama pull llama3 \
    && ollama pull nomic-embed-text \
    && pkill ollama

# Make the entrypoint executable
RUN chmod +x docker-entrypoint.sh
RUN chmod +x start.sh

# Expose port
EXPOSE $PORT

# Start the application using the entrypoint script
CMD ["./docker-entrypoint.sh"]
