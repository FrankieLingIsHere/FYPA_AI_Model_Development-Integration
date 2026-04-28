# AI Safety Inspector

This project is a web-based AI Safety Inspector tool that analyzes workplace scenes for hazards and PPE violations using large language models via Ollama. It features two variants:
- **Deepseek R1 7B** (no RAG)
- **Llama3** (with RAG and incident similarity)

## Features
- Modern, responsive UI
- Two-column results layout (Hazards & Suggested Actions)
- Loading spinner for analysis feedback
- Detailed cards for summary, persons, PPE, hazards, and actions
- Local Python server for static file hosting

## Requirements
- **Python 3.x** (for local web server)
- **Ollama** (for running LLMs locally)
- **Deepseek R1 7B** and **Llama3** models downloaded in Ollama

## Setup Instructions

### 1. Install Python
Download and install Python 3.x from [python.org](https://www.python.org/downloads/).

### 2. Install Ollama
Download and install Ollama from [ollama.com/download](https://ollama.com/download).

### 3. Download Models in Ollama
Open a terminal and run:
```
ollama pull deepseek-r1:7b
ollama pull llama3
```

### 4. Set CORS for Ollama (if using browser)
To allow browser access, set the environment variable before starting Ollama:
- On Windows (PowerShell):
  ```powershell
  $env:OLLAMA_ORIGINS="*"
  ollama serve
  ```
- On Mac/Linux:
  ```bash
  export OLLAMA_ORIGINS="*"
  ollama serve
  ```

### 5. Start the Python Server
Run the batch file:
```
start.bat
```
Or manually:
```
python -m http.server 8001
```

### 6. Open the Application
Visit:
- [http://localhost:8001/index.html](http://localhost:8001/index.html) (Deepseek variant)
- [http://localhost:8001/llama3_variant/index_llama.html](http://localhost:8001/llama3_variant/index_llama.html) (Llama3 variant)

## File Structure
- `index.html` — Main app (Deepseek)
- `llama3_variant/index_llama.html` — Llama3 variant
- `script.js` — Main logic (Deepseek)
- `llama3_variant/script_llama.js` — Llama3 logic
- `style.css` — Unified styles
- `libs/d3-dsv.js` — CSV parsing for RAG
- `start.bat` — Batch file to start server and open browser

## Team & License
See `LICENSE` for details. Contributions welcome!
