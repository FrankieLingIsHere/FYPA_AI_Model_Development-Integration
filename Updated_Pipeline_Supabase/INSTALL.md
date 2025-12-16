# 🚀 LUNA Supabase Edition - Installation Guide

Complete step-by-step installation guide for the Supabase-backed PPE Safety Monitor.

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Supabase Setup](#supabase-setup)
3. [Python Environment](#python-environment)
4. [Configuration](#configuration)
5. [Model Setup](#model-setup)
6. [Testing](#testing)
7. [Running the Application](#running-the-application)
8. [Troubleshooting](#troubleshooting)

---

## 1️⃣ Prerequisites

### Required Software

- **Python 3.10 or 3.11** (3.12 may have compatibility issues)
- **Git** for cloning the repository
- **NVIDIA GPU** with 8GB+ VRAM (for YOLO inference)
- **CUDA Toolkit** 11.8 or 12.1 (for GPU acceleration)
- **Ollama** for LLaVA and Llama3 models

### Accounts

- **Supabase Account** - Free tier available at [supabase.com](https://supabase.com)

---

## 2️⃣ Supabase Setup

### Step 1: Create Supabase Project

1. Go to [app.supabase.com](https://app.supabase.com)
2. Click **"New Project"**
3. Fill in project details:
   - **Name**: `luna-ppe-monitor` (or your choice)
   - **Database Password**: Generate a strong password (save this!)
   - **Region**: Choose closest to your location
4. Click **"Create new project"**
5. Wait 2-3 minutes for project to be provisioned

### Step 2: Get API Credentials

1. In your Supabase project dashboard, go to **Settings** → **API**
2. Copy and save these values:
   - **Project URL** (e.g., `https://abcdefgh.supabase.co`)
   - **Service Role Key** (secret key - starts with `eyJ...`)
   - **anon/public key** (not needed for this project)

### Step 3: Get Database Connection String

1. Go to **Settings** → **Database**
2. Scroll down to **Connection string** → **URI**
3. Copy the connection string
4. Replace `[YOUR-PASSWORD]` with your database password from Step 1
5. Save the complete connection string (e.g., `postgresql://postgres:yourpassword@db.abcdefgh.supabase.co:5432/postgres`)

### Step 4: Create Database Tables

1. Go to **SQL Editor** in the left sidebar
2. Click **New query**
3. Copy and paste this SQL:

```sql
-- Detection Events Table
CREATE TABLE IF NOT EXISTS public.detection_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id VARCHAR(50) UNIQUE NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    person_count INTEGER DEFAULT 0,
    violation_count INTEGER DEFAULT 0,
    severity VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_detection_events_report_id ON public.detection_events(report_id);
CREATE INDEX idx_detection_events_timestamp ON public.detection_events(timestamp);

-- Violations Table
CREATE TABLE IF NOT EXISTS public.violations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id VARCHAR(50) NOT NULL REFERENCES public.detection_events(report_id) ON DELETE CASCADE,
    violation_summary TEXT,
    caption TEXT,
    nlp_analysis JSONB,
    detection_data JSONB,
    original_image_key VARCHAR(500),
    annotated_image_key VARCHAR(500),
    report_html_key VARCHAR(500),
    report_pdf_key VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_violations_report_id ON public.violations(report_id);

-- Flood Logs Table
CREATE TABLE IF NOT EXISTS public.flood_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(50) NOT NULL,
    report_id VARCHAR(50),
    message TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_flood_logs_event_type ON public.flood_logs(event_type);
CREATE INDEX idx_flood_logs_created_at ON public.flood_logs(created_at);

-- Enable Row Level Security
ALTER TABLE public.detection_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.violations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flood_logs ENABLE ROW LEVEL SECURITY;

-- Create policies (allow service role full access)
CREATE POLICY "Enable all for service role" ON public.detection_events FOR ALL USING (true);
CREATE POLICY "Enable all for service role" ON public.violations FOR ALL USING (true);
CREATE POLICY "Enable all for service role" ON public.flood_logs FOR ALL USING (true);
```

4. Click **Run** (or press Ctrl+Enter)
5. Verify "Success. No rows returned" message

### Step 5: Create Storage Buckets

**Option A: Using SQL**

1. In SQL Editor, create a new query:

```sql
-- Create storage buckets
INSERT INTO storage.buckets (id, name, public) 
VALUES 
  ('violation-images', 'violation-images', false),
  ('reports', 'reports', false)
ON CONFLICT (id) DO NOTHING;

-- Set up access policies
CREATE POLICY "Service role full access on violation-images"
ON storage.objects FOR ALL 
TO service_role
USING (bucket_id = 'violation-images');

CREATE POLICY "Service role full access on reports"
ON storage.objects FOR ALL 
TO service_role
USING (bucket_id = 'reports');
```

2. Click **Run**

**Option B: Using Dashboard**

1. Go to **Storage** in the left sidebar
2. Click **New bucket**
3. Create first bucket:
   - **Name**: `violation-images`
   - **Public bucket**: ❌ (keep it private)
   - Click **Create bucket**
4. Create second bucket:
   - **Name**: `reports`
   - **Public bucket**: ❌ (keep it private)
   - Click **Create bucket**

### Step 6: Verify Setup

1. Go to **Table Editor**
2. Verify you see 3 tables: `detection_events`, `violations`, `flood_logs`
3. Go to **Storage**
4. Verify you see 2 buckets: `violation-images`, `reports`

---

## 3️⃣ Python Environment

### Step 1: Clone Repository

```bash
cd /path/to/your/projects
git clone https://github.com/FrankieLingIsHere/FYPA_AI_Model_Development-Integration.git
cd FYPA_AI_Model_Development-Integration/Updated_Pipeline_Supabase
```

### Step 2: Create Virtual Environment

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This will install:
- Flask (web framework)
- YOLOv8 (Ultralytics)
- PyTorch (deep learning)
- OpenCV (computer vision)
- Supabase Python client
- psycopg2-binary (Postgres driver)
- And more...

**Note:** Installation may take 5-10 minutes depending on your internet speed.

---

## 4️⃣ Configuration

### Step 1: Create .env File

Copy the example environment file:

```bash
cp .env.example .env
```

### Step 2: Edit .env File

Open `.env` in a text editor and fill in your Supabase credentials:

```bash
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_DB_URL=postgresql://postgres:yourpassword@db.your-project.supabase.co:5432/postgres

# Storage Bucket Names (optional)
SUPABASE_IMAGES_BUCKET=violation-images
SUPABASE_REPORTS_BUCKET=reports

# Signed URL TTL (optional)
SUPABASE_SIGNED_URL_TTL_SECONDS=3600

# PDF Upload (optional)
UPLOAD_PDF=false
```

**Security Note:** Never commit your `.env` file to Git!

### Step 3: Verify .gitignore

Ensure `.gitignore` contains:
```
.env
.env.local
.env.*.local
```

---

## 5️⃣ Model Setup

### Step 1: Install Ollama

**Windows:**
1. Download from [ollama.ai](https://ollama.ai)
2. Run installer
3. Ollama will start automatically

**Linux:**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

**Mac:**
```bash
brew install ollama
```

### Step 2: Pull Required Models

Open a terminal and run:

```bash
# Image captioning (30-60 sec per image)
ollama pull llava:7b

# Report generation with NLP
ollama pull llama3

# RAG embeddings
ollama pull nomic-embed-text
```

**Note:** These downloads are large:
- `llava:7b`: ~4.7 GB
- `llama3`: ~4.7 GB
- `nomic-embed-text`: ~274 MB

Total: ~10 GB. Plan accordingly!

### Step 3: Copy YOLOv8 Weights

Copy the trained YOLO model from the original pipeline:

```bash
# From Updated_Pipeline_Supabase directory
cp -r ../Updated_Pipeline/Results ./
```

Or download from your model training location.

Expected structure:
```
Updated_Pipeline_Supabase/
└── Results/
    └── ppe_yolov86/
        └── weights/
            └── best.pt
```

---

## 6️⃣ Testing

### Test 1: Database Connection

```bash
python -c "from pipeline.backend.core.supabase_db import create_db_manager_from_env; db = create_db_manager_from_env(); print('✓ Database connected!')"
```

Expected output: `✓ Database connected!`

### Test 2: Storage Connection

```bash
python -c "from pipeline.backend.core.supabase_storage import create_storage_manager_from_env; storage = create_storage_manager_from_env(); print('✓ Storage connected!')"
```

Expected output: `✓ Storage connected!`

### Test 3: Ollama Models

```bash
ollama list
```

Expected output should show:
- `llava:7b`
- `llama3:latest`
- `nomic-embed-text:latest`

### Test 4: YOLO Model

```bash
python -c "from ultralytics import YOLO; model = YOLO('Results/ppe_yolov86/weights/best.pt'); print('✓ YOLO model loaded!')"
```

Expected output: `✓ YOLO model loaded!`

---

## 7️⃣ Running the Application

### Start Report Viewer

```bash
python view_reports.py
```

Open browser to: `http://localhost:5001`

You should see the LUNA Reports interface (initially empty).

### Test with Sample Data (Optional)

If you have existing reports in the original `Updated_Pipeline`:

```bash
python migrate_to_supabase.py --dry-run --limit 1
```

This previews migrating 1 report without actually doing it.

To actually migrate:

```bash
python migrate_to_supabase.py --limit 5
```

Migrates the first 5 reports.

Refresh `http://localhost:5001` to see migrated reports.

---

## 8️⃣ Troubleshooting

### "Module not found" errors

**Solution:** Make sure virtual environment is activated:
```bash
# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### "SUPABASE_URL must be set"

**Solution:** Verify `.env` file exists and contains correct values.

### "Connection refused" to Supabase

**Solutions:**
1. Check project is not paused (Supabase free tier pauses after inactivity)
2. Verify `SUPABASE_URL` and `SUPABASE_DB_URL` are correct
3. Check internet connection

### "Bucket not found"

**Solutions:**
1. Verify buckets exist in Supabase Dashboard → Storage
2. Check bucket names in `.env` match actual bucket names
3. Ensure bucket policies allow service role access

### YOLO model errors

**Solutions:**
1. Verify `Results/ppe_yolov86/weights/best.pt` exists
2. Check GPU is available: `python -c "import torch; print(torch.cuda.is_available())"`
3. If no GPU, edit `pipeline/config.py`: change `device: 'cuda'` to `device: 'cpu'`

### Ollama connection errors

**Solutions:**
1. Check Ollama is running: `ollama list`
2. Restart Ollama service
3. Verify models are installed: `ollama list`

### Images not loading in reports

**Solutions:**
1. Check signed URL TTL hasn't expired
2. Verify storage keys in database are correct
3. Test signed URL generation manually

---

## ✅ Installation Complete!

You now have a fully functional Supabase-backed PPE Safety Monitor!

### Next Steps:

1. **Start monitoring** - Run your inference pipeline
2. **View reports** - Access `http://localhost:5001`
3. **Monitor database** - Check Supabase dashboard for records
4. **Scale** - Reports are now cloud-accessible!

---

## 📞 Support

If you encounter issues:

1. Check the [README.md](README.md) for configuration details
2. Review error logs in terminal
3. Verify Supabase dashboard shows tables and buckets
4. Check `.env` file has correct credentials

---

**🌙 LUNA Supabase Edition - You're all set!**
