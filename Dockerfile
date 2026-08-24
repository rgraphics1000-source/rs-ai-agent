# Use official lightweight Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8 \
    PORT=10000

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Ensure upload directory exists and has full permissions
RUN mkdir -p static/uploads && chmod -R 777 static/uploads

# Expose ports (10000 for Render, 7860 for Hugging Face, 8000 for VPS/local)
EXPOSE 10000
EXPOSE 8000
EXPOSE 7860

# Launch FastAPI app with Uvicorn on dynamic PORT (default 10000 for Render)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
