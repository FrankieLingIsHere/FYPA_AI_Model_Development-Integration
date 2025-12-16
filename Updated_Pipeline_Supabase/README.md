# 🌙 LUNA PPE Safety Monitor - Supabase Edition

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)](https://flask.palletsprojects.com/)
[![Supabase](https://img.shields.io/badge/Supabase-Backend-brightgreen.svg)](https://supabase.com/)
[![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-orange.svg)](https://docs.ultralytics.com/)

**Complete AI-powered PPE compliance monitoring system with cloud-based reporting using Supabase (Postgres + Storage).**

---

## 🚀 What's New in Supabase Edition?

This version replaces SQLite and local file storage with **Supabase** for cloud-based operation:

- ✅ **Postgres Database** - Violations stored in `detection_events`, `violations`, and `flood_logs` tables
- ✅ **Private Storage Buckets** - Report artifacts in `violation-images` and `reports` buckets
- ✅ **Signed URLs** - Secure access to private images and reports from any device
- ✅ **Cloud-Ready** - Access reports from anywhere with proper authentication
- ✅ **Multi-Device Support** - View reports on desktop, tablet, or mobile
- ✅ **Scalable Storage** - No more disk space limitations

---

## 📋 Prerequisites

1. **Supabase Account** - Create a free account at [supabase.com](https://supabase.com)
2. **Python 3.10+** - With pip
3. **Ollama** - For LLaVA image captioning and Llama3 report generation
4. **NVIDIA GPU** - 8GB+ VRAM recommended for YOLOv8 inference

---

## 🗄️ Supabase Setup

### 1. Create Supabase Project

1. Go to [app.supabase.com](https://app.supabase.com)
2. Click **"New Project"**
3. Enter project details and create
4. Save your **Project URL** and **Service Role Key** (found in Settings → API)

### 2. Create Database Tables

Run this SQL in your Supabase SQL Editor:

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
    
    -- Storage keys (not local paths)
    original_image_key VARCHAR(500),
    annotated_image_key VARCHAR(500),
    report_html_key VARCHAR(500),
    report_pdf_key VARCHAR(500),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_violations_report_id ON public.violations(report_id);

-- Flood Logs Table (for tracking system events)
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

-- Enable Row Level Security (RLS)
ALTER TABLE public.detection_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.violations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flood_logs ENABLE ROW LEVEL SECURITY;

-- Create policies (adjust based on your auth requirements)
-- For now, allow service role to do everything
CREATE POLICY "Enable all for service role" ON public.detection_events FOR ALL USING (true);
CREATE POLICY "Enable all for service role" ON public.violations FOR ALL USING (true);
CREATE POLICY "Enable all for service role" ON public.flood_logs FOR ALL USING (true);
```

### 3. Create Storage Buckets

Run this SQL to create private storage buckets:

```sql
-- Create buckets (run in SQL editor or via Supabase Dashboard → Storage)
INSERT INTO storage.buckets (id, name, public) 
VALUES 
  ('violation-images', 'violation-images', false),
  ('reports', 'reports', false)
ON CONFLICT (id) DO NOTHING;

-- Set up policies for bucket access
-- Allow service role to upload/read/delete
CREATE POLICY "Service role can do everything on violation-images"
ON storage.objects FOR ALL 
TO service_role
USING (bucket_id = 'violation-images');

CREATE POLICY "Service role can do everything on reports"
ON storage.objects FOR ALL 
TO service_role
USING (bucket_id = 'reports');
```

Or create buckets via Supabase Dashboard:
1. Go to **Storage** → **New bucket**
2. Create `violation-images` (Private)
3. Create `reports` (Private)

### 4. Get Database Connection String

In Supabase Dashboard:
1. Go to **Settings** → **Database**
2. Find **Connection string** → **URI**
3. Copy the connection string (it looks like: `postgresql://postgres:[password]@db.[project].supabase.co:5432/postgres`)

---

## ⚙️ Environment Configuration

Create a `.env` file in the `Updated_Pipeline_Supabase/` directory:

```bash
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key-here
SUPABASE_DB_URL=postgresql://postgres:[password]@db.[project].supabase.co:5432/postgres

# Storage Bucket Names (optional, defaults shown)
SUPABASE_REPORTS_BUCKET=reports
SUPABASE_IMAGES_BUCKET=violation-images

# Signed URL Configuration (optional)
SUPABASE_SIGNED_URL_TTL_SECONDS=3600  # 1 hour default

# Upload Options (optional)
UPLOAD_PDF=false  # Set to true to enable PDF generation and upload
```

**Security Note**: Never commit your `.env` file to version control. Add it to `.gitignore`.

---

## 📦 Installation

### 1. Install Python Dependencies

```bash
cd Updated_Pipeline_Supabase
pip install -r requirements.txt
```

### 2. Install Ollama

Download and install Ollama from [ollama.ai](https://ollama.ai)

Then pull required models:

```bash
ollama pull llava:7b          # Image captioning (30-60 sec per image)
ollama pull llama3            # Report generation
ollama pull nomic-embed-text  # RAG embeddings
```

### 3. Set Up Model Weights

Copy YOLOv8 weights from the original Updated_Pipeline:

```bash
cp -r ../Updated_Pipeline/Results ./
```

### 4. Verify Setup

Run the validation tests:

```bash
# Full system validation
python test_setup.py

# Quick smoke test (database round-trip)
python smoke_test.py
```

Both tests should pass before proceeding.

---

## 🎮 Usage

### Quick Start (Recommended)

Use the startup scripts for easiest setup:

**Linux/Mac:**
```bash
./start.sh
```

**Windows:**
```bash
start.bat
```

The scripts will:
- Check for `.env` file
- Create virtual environment if needed
- Install dependencies
- Start the LUNA application

### Manual Start

```bash
# Activate virtual environment
source venv/bin/activate  # Windows: venv\Scripts\activate

# Start main application
python luna_app.py
```

Then open your browser to: `http://localhost:5000`

### Alternative: Report Viewer Only

If you only want to view existing reports without live monitoring:

```bash
python view_reports.py
```

Then open: `http://localhost:5001`

### Features

- **Live Monitoring** - Real-time PPE detection with webcam
- **Report Management** - Browse violations stored in Supabase
- **Cloud Access** - Access reports from any device
- **Signed URLs** - Secure access to private images and reports
- **Standalone** - No dependencies on parent folder at runtime

---

## 🔌 API Endpoints

All endpoints remain the same as the original LUNA system:

### Violations
- `GET /api/violations` - List violations (from Supabase Postgres)
- `GET /report/<report_id>` - View report (fetches from Supabase)
- `GET /image/<report_id>/<filename>` - Get image (signed URL from Supabase Storage)

### Live Streaming
- `GET /api/live/stream` - Video stream
- `POST /api/live/start` - Start monitoring
- `POST /api/live/stop` - Stop monitoring

### System
- `GET /api/system/info` - System information

---

## 🗂️ Storage Structure

### Supabase Storage Buckets

**`violation-images` bucket:**
```
violation-images/
├── 20231205_143022/
│   ├── original.jpg
│   └── annotated.jpg
├── 20231205_143156/
│   ├── original.jpg
│   └── annotated.jpg
...
```

**`reports` bucket:**
```
reports/
├── 20231205_143022/
│   ├── report.html
│   └── report.pdf (optional)
├── 20231205_143156/
│   ├── report.html
│   └── report.pdf (optional)
...
```

### Postgres Database Schema

**`detection_events` table:**
- `id` - UUID primary key
- `report_id` - Unique report identifier (e.g., `20231205_143022`)
- `timestamp` - Detection timestamp
- `person_count` - Number of people detected
- `violation_count` - Number of violations
- `severity` - Violation severity (HIGH/MEDIUM/LOW)

**`violations` table:**
- `id` - UUID primary key
- `report_id` - Foreign key to detection_events
- `violation_summary` - Text summary
- `caption` - LLaVA image caption
- `nlp_analysis` - JSONB with Llama3 analysis
- `detection_data` - JSONB with YOLO detections
- `original_image_key` - Storage key (e.g., `violation-images/20231205_143022/original.jpg`)
- `annotated_image_key` - Storage key
- `report_html_key` - Storage key
- `report_pdf_key` - Storage key (optional)

---

## 🔐 Security Best Practices

1. **Use Service Role Key** - Only on backend, never in frontend
2. **Enable RLS** - Row Level Security on all tables
3. **Private Buckets** - Keep all buckets private, use signed URLs
4. **Environment Variables** - Never commit `.env` file
5. **Signed URL TTL** - Set appropriate expiration times
6. **HTTPS Only** - Always use HTTPS in production

---

## 🛠️ Troubleshooting

### "Invalid API key" Error
- Check `SUPABASE_SERVICE_ROLE_KEY` in `.env`
- Verify you're using the **service role** key, not the anon key

### "Bucket not found" Error
- Verify buckets exist in Supabase Dashboard → Storage
- Check bucket names match environment variables

### "Connection refused" Error
- Check `SUPABASE_URL` is correct
- Verify project is not paused (free tier)

### Images Not Loading
- Check signed URL TTL hasn't expired
- Verify bucket policies allow service role access
- Check storage keys in database are correct

---

## 📊 Migration from Local Storage

To migrate existing reports from the local SQLite version:

1. Export local violations from SQLite database
2. Upload images to Supabase Storage buckets
3. Insert records into Postgres with storage keys
4. Update keys to point to Supabase Storage

A migration script is provided: `migrate_to_supabase.py`

---

## 🔄 Differences from Original Pipeline

| Feature | Original (Updated_Pipeline) | Supabase Edition |
|---------|---------------------------|------------------|
| Database | SQLite (local file) | Supabase Postgres (cloud) |
| Image Storage | Local `pipeline/violations/` | Supabase Storage (private buckets) |
| Report Storage | Local filesystem | Supabase Storage |
| Image Access | Direct file serving | Signed URLs |
| Multi-Device | Single machine only | Access from anywhere |
| Scalability | Limited by disk space | Cloud-scalable |
| Backup | Manual file copy | Supabase automatic backups |

---

## 📚 Additional Documentation

- **[Supabase Python Docs](https://supabase.com/docs/reference/python/introduction)**
- **[Supabase Storage](https://supabase.com/docs/guides/storage)**
- **[Postgres Client Library](https://www.psycopg.org/psycopg3/docs/)**

---

## 🙏 Credits

- **Original LUNA System** - FYP Team A
- **YOLOv8** - Ultralytics
- **LLaVA** - Visual instruction tuning
- **Llama3** - Meta AI
- **Supabase** - Open source Firebase alternative

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](../LICENSE) file for details.

---

**🌙 LUNA Supabase Edition - Cloud-Powered PPE Safety Monitoring**

*Your safety data, accessible anywhere!*
