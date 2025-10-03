@echo off
echo Starting Python HTTP server on port 8001...
start "PythonServer" python -m http.server 8001

echo Waiting for server to start...
timeout /t 4 /nobreak > nul

echo Opening application pages in the browser...
start http://localhost:8001/index.html
start http://localhost:8001/llama3_variant/index_llama.html

echo Done.
