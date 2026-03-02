#!/bin/bash

# Navigate to the script's directory
cd "$(dirname "$0")"

echo "========================================"
echo "  Starting S3 Team Share App...        "
echo "========================================"

# Check for Python 3
if ! command -v python3 &> /dev/null
then
    echo "[ERROR] Python 3 not found! Please install it."
    exit 1
fi

# Create Virtual Environment if not exists
if [ ! -d ".venv" ]; then
    echo "Initializing local environment..."
    python3 -m venv .venv
fi

# Activate venv and install dependencies
source .venv/bin/activate
echo "Checking dependencies..."
pip install -r requirements.txt --quiet

# Run the app
echo "Starting UI..."
streamlit run app.py --server.port 8501
