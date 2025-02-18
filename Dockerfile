FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    git \
    pandoc \
    poppler-utils \
    tesseract-ocr \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir \
    finnhub-python==2.4.22 \
    yfinance==0.2.52 \
    pandas==2.0.3 \
    streamlit==1.41.1 \
    autogen==0.7.2 \
    openai==1.60.2 \
    PyMuPDF==1.25.3

# Create necessary directories
RUN mkdir -p /app/report /app/data /app/logs

# Copy the application code
COPY finrobot /app/finrobot/
COPY tutorials_beginner /app/tutorials_beginner/
COPY README.md .

# Create config directory and add configuration files
RUN mkdir -p /app/config

# Create OAI config template (will be populated at runtime)
RUN echo '[{"model": "gpt-4", "api_key": ""}]' > /app/config/OAI_CONFIG_LIST

# Create API keys template (will be populated at runtime)
RUN echo '{\
    "FINNHUB_API_KEY": "",\
    "FMP_API_KEY": "",\
    "SEC_API_KEY": "",\
    "REDDIT_CLIENT_ID": "",\
    "REDDIT_CLIENT_SECRET": "",\
    "OPENAI_API_KEY": ""\
}' > /app/config/config_api_keys

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV CONFIG_DIR=/app/config
ENV REPORT_DIR=/app/report
ENV DATA_DIR=/app/data
ENV LOG_DIR=/app/logs

# Expose port for Streamlit
EXPOSE 8501

# Create entrypoint script
RUN echo '#!/bin/bash\n\
# Update API configurations with environment variables\n\
echo "[{\"model\": \"gpt-4\", \"api_key\": \"$OPENAI_API_KEY\"}]" > /app/config/OAI_CONFIG_LIST\n\
\n\
echo "{\n\
  \"FINNHUB_API_KEY\": \"$FINNHUB_API_KEY\",\n\
  \"FMP_API_KEY\": \"$FMP_API_KEY\",\n\
  \"SEC_API_KEY\": \"$SEC_API_KEY\",\n\
  \"REDDIT_CLIENT_ID\": \"$REDDIT_CLIENT_ID\",\n\
  \"REDDIT_CLIENT_SECRET\": \"$REDDIT_CLIENT_SECRET\",\n\
  \"OPENAI_API_KEY\": \"$OPENAI_API_KEY\"\n\
}" > /app/config/config_api_keys\n\
\n\
# Start Streamlit\n\
streamlit run finrobot/web/app.py --server.port=8501 --server.address=0.0.0.0' > /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

# Set the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"] 