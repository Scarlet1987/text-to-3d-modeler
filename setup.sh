#!/bin/bash
# Setup for text-to-3d-modeler. Run once:  bash setup.sh
set -e
cd "$(dirname "$0")"

echo "=== Python ==="
python3 --version || { echo "Install Python 3.10+ first"; exit 1; }

echo "=== Virtual environment ==="
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip

echo "=== Dependencies (this takes a few minutes) ==="
.venv/bin/pip install -q cadquery fastapi uvicorn requests pymupdf

echo "=== LLM backend (compiles — grab a coffee) ==="
.venv/bin/pip install -q llama-cpp-python

echo "=== Model download (4.7GB) ==="
mkdir -p models
if [ ! -f models/Qwen3-8B-Q4_K_M.gguf ]; then
    .venv/bin/python -c "
from huggingface_hub import hf_hub_download
hf_hub_download('Qwen/Qwen3-8B-GGUF', 'Qwen3-8B-Q4_K_M.gguf',
                local_dir='models', local_dir_use_symlinks=False)
print('model ready')
" 2>/dev/null || {
    echo "huggingface_hub not found, installing..."
    .venv/bin/pip install -q huggingface_hub
    .venv/bin/python -c "
from huggingface_hub import hf_hub_download
hf_hub_download('Qwen/Qwen3-8B-GGUF', 'Qwen3-8B-Q4_K_M.gguf',
                local_dir='models', local_dir_use_symlinks=False)
print('model ready')
"
}
else
    echo "model already present"
fi

echo ""
echo "=== Done ==="
echo "Start the GUI:  .venv/bin/python -m server.app"
echo "Then open:      http://localhost:8000"
