# Updated_Pipeline_Supabase - Standalone Module

## Overview

This folder is a **fully standalone, self-contained** implementation of the CASM PPE Safety Monitor system with Supabase backend integration. It can be run independently without any dependencies on the parent repository folders.

## What Makes It Standalone?

### ✅ All Code Included
- **Complete pipeline implementation** - All backend modules included
- **Frontend web interface** - Full SPA with all pages and assets
- **NLP/RAG system** - DOSH guidelines data and RAG implementation
- **Helper scripts** - Caption generation, model downloads, utilities

### ✅ No External Dependencies at Runtime
- All imports are from within this folder or installed packages
- No `sys.path` manipulation needed to reference parent folders
- No relative imports outside the module boundary

### ✅ Configuration Self-Contained
- Single `.env` file for all configuration
- Config module (`pipeline/config.py`) handles all settings
- No need to modify code for different deployments

### ✅ Documentation Complete
- `README.md` - Full setup and usage guide
- `INSTALL.md` - Detailed installation instructions
- `QUICKSTART.md` - 10-minute quick start
- `.env.example` - Configuration template

## Folder Structure

```
Updated_Pipeline_Supabase/
├── casm_app.py                    # Main application (Flask server + live monitoring)
├── view_reports.py                # Alternative: Report viewer only
├── test_setup.py                  # Validation: Test all components
├── smoke_test.py                  # Validation: Quick round-trip test
├── start.sh / start.bat           # Startup scripts (Unix/Windows)
│
├── .env.example                   # Configuration template
├── requirements.txt               # Python dependencies
│
├── pipeline/                      # Core backend modules
│   ├── config.py                  # Central configuration
│   ├── backend/
│   │   ├── core/                 # Core modules
│   │   │   ├── supabase_db.py           # Supabase database manager
│   │   │   ├── supabase_storage.py     # Supabase storage manager
│   │   │   ├── supabase_report_generator.py  # Report generator with Supabase
│   │   │   ├── violation_detector.py   # PPE violation detection
│   │   │   ├── image_processor.py      # Image annotation
│   │   │   ├── yolo_stream.py          # YOLO streaming
│   │   │   └── ...
│   │   └── integration/          # Integration modules
│   │       ├── caption_generator.py    # LLaVA image captioning
│   │       ├── local_llama.py          # Llama3 report generation
│   │       └── ...
│   └── ...
│
├── frontend/                      # Web interface (SPA)
│   ├── index.html
│   ├── css/style.css
│   └── js/
│       ├── app.js                # Main app
│       ├── pages/                # All page components
│       │   ├── home.js
│       │   ├── live.js           # Live monitoring
│       │   ├── reports.js
│       │   └── ...
│       └── ...
│
├── NLP_CASM/                      # RAG data and system
│   ├── Trim1.csv                 # DOSH guidelines dataset
│   └── ...
│
├── Results/                       # YOLO model weights (gitignored)
│   └── ppe_yolov86/
│       └── weights/
│           └── best.pt           # YOLOv8 trained model
│
└── [Helper scripts]
    ├── infer_image.py            # Image inference
    ├── caption_image.py          # Caption generation
    ├── download_llava.py         # Model downloads
    ├── download_llama3.py
    └── ...
```

## How to Run (Standalone)

### Method 1: Quick Start (Recommended)

```bash
# Linux/Mac
./start.sh

# Windows
start.bat
```

### Method 2: Manual

```bash
# Navigate to this folder
cd Updated_Pipeline_Supabase

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Supabase credentials

# Run validation
python test_setup.py

# Start application
python casm_app.py
```

Open browser to `http://localhost:5000`

## Runtime Dependencies

### Required
- **Python 3.10+** - Runtime environment
- **Supabase Account** - Cloud backend (free tier available)
- **Ollama** - For LLaVA and Llama3 models
- **NVIDIA GPU** - Recommended for YOLO inference (CPU fallback available)

### Python Packages
All listed in `requirements.txt`:
- Flask, OpenCV, PyTorch, Ultralytics (YOLO)
- Supabase Python client, psycopg2
- ChromaDB, requests, numpy, pandas
- And more (see requirements.txt)

### External Services
- **Supabase** - Cloud Postgres + Storage
  - Project URL, Service Role Key, DB URL needed
  - Tables must be created (SQL in README.md)
  - Storage buckets must be created

- **Ollama** - Local AI models
  - `ollama pull llava:7b`
  - `ollama pull llama3`
  - `ollama pull nomic-embed-text`

### Model Files (Not in Repo)
- **YOLOv8 Weights** - `Results/ppe_yolov86/weights/best.pt`
  - Must be copied from `../Updated_Pipeline/Results/`
  - Or train your own model
  - ~100MB file, gitignored

## Key Features of Supabase Integration

### Database (Postgres)
- `detection_events` - Main violation events
- `violations` - Detailed violation data with storage keys
- `flood_logs` - System event logging

### Storage (Private Buckets)
- `violation-images` - Original and annotated images
- `reports` - HTML and optional PDF reports
- Signed URLs for secure access (configurable TTL)

### Comparison with Original Pipeline

| Feature | Original (Updated_Pipeline) | Supabase Edition |
|---------|---------------------------|------------------|
| Database | SQLite (local file) | Supabase Postgres (cloud) |
| Image Storage | Local filesystem | Supabase Storage (private buckets) |
| Report Access | Single machine only | Access from anywhere |
| Scalability | Limited by disk space | Cloud-scalable |
| Multi-device | No | Yes |
| Backup | Manual | Automatic (Supabase) |

## Validation

Before running the application, validate your setup:

```bash
# Full validation (checks everything)
python test_setup.py

# Quick smoke test (database round-trip)
python smoke_test.py
```

Both should pass before proceeding.

## Troubleshooting

### "Module not found" errors
- Ensure you're in the correct directory
- Activate virtual environment
- Install dependencies: `pip install -r requirements.txt`

### Supabase connection errors
- Check `.env` file has correct credentials
- Verify Supabase project is not paused
- Run `python smoke_test.py` for diagnostics

### Model weights not found
- Copy from parent: `cp -r ../Updated_Pipeline/Results ./`
- Or train your own YOLOv8 model

## Development Notes

### Making Changes
- All code is self-contained in this folder
- Modify `pipeline/config.py` for configuration changes
- No need to synchronize with parent repository
- Can be developed and deployed independently

### Deployment
- Copy entire folder to deployment environment
- Set environment variables (`.env` or system env vars)
- Install dependencies
- Run startup script or `python casm_app.py`

### Testing
- Unit tests can be added to `tests/` folder
- Use `test_setup.py` as validation suite
- `smoke_test.py` for quick sanity checks

## License

Same as parent repository (MIT License).

## Credits

Based on the CASM PPE Safety Monitor system by FYP Team A.
Refactored for standalone operation with Supabase backend integration.

---

**🌙 CASM Supabase Edition - Standalone and Ready to Deploy!**
