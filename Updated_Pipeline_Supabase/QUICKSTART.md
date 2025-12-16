# ⚡ Quick Start Guide - LUNA Supabase Edition

Get up and running in 10 minutes!

---

## 📋 Prerequisites

Before you start, make sure you have:

- ✅ Python 3.10 or 3.11 installed
- ✅ NVIDIA GPU with CUDA (or be prepared for slower CPU inference)
- ✅ Supabase account created ([sign up free](https://supabase.com))
- ✅ Ollama installed ([download here](https://ollama.ai))

---

## 🚀 Quick Setup (5 Steps)

### Step 1: Clone and Setup (2 min)

```bash
# Clone repository
git clone https://github.com/FrankieLingIsHere/FYPA_AI_Model_Development-Integration.git
cd FYPA_AI_Model_Development-Integration/Updated_Pipeline_Supabase

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Supabase Setup (3 min)

1. Go to [app.supabase.com](https://app.supabase.com)
2. Create a new project (remember the password!)
3. Go to **Settings** → **API** and copy:
   - Project URL
   - Service Role Key
4. Go to **Settings** → **Database** and copy:
   - Connection String (URI format)
5. Go to **SQL Editor** and run the setup SQL (see below)

**Setup SQL:**
```sql
-- Run this in Supabase SQL Editor
-- Copy from README.md "Create Database Tables" section
-- Takes ~30 seconds
```

### Step 3: Configuration (1 min)

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your favorite editor
nano .env  # or: code .env, vim .env, etc.

# Fill in your Supabase credentials:
# - SUPABASE_URL
# - SUPABASE_SERVICE_ROLE_KEY
# - SUPABASE_DB_URL
```

### Step 4: Download Models (3 min)

```bash
# Pull Ollama models (downloads ~10GB)
ollama pull llava:7b
ollama pull llama3
ollama pull nomic-embed-text

# Copy YOLO weights from original pipeline
cp -r ../Updated_Pipeline/Results ./
```

### Step 5: Test & Run (1 min)

```bash
# Validate setup
python test_setup.py

# Start report viewer
python view_reports.py
```

Open browser to: **http://localhost:5001**

---

## 🎯 That's It!

You're now running LUNA with Supabase backend! 

### What You Can Do Now:

✅ **View Reports** - Access reports from any device  
✅ **Cloud Storage** - Images and reports in Supabase  
✅ **Postgres Database** - Scalable violation tracking  
✅ **Signed URLs** - Secure access to private files  

---

## 📝 Next Steps

### Migrate Existing Data (Optional)

If you have reports from the local SQLite version:

```bash
# Preview migration
python migrate_to_supabase.py --dry-run --limit 5

# Actually migrate
python migrate_to_supabase.py --limit 10
```

### Generate New Reports

Use your existing pipeline code, but import the Supabase report generator:

```python
from pipeline.backend.core.supabase_report_generator import create_supabase_report_generator
from pipeline.config import *

config = {
    'OLLAMA_CONFIG': OLLAMA_CONFIG,
    'RAG_CONFIG': RAG_CONFIG,
    'REPORT_CONFIG': REPORT_CONFIG,
    'BRAND_COLORS': BRAND_COLORS,
    'REPORTS_DIR': REPORTS_DIR,
    'VIOLATIONS_DIR': VIOLATIONS_DIR,
    'SUPABASE_CONFIG': SUPABASE_CONFIG
}

generator = create_supabase_report_generator(config)

# Generate report (automatically uploads to Supabase)
result = generator.generate_report(report_data)
```

### Access from Other Devices

Since reports are in Supabase, you can:

1. **Install viewer on another machine**
2. **Use same `.env` file**
3. **Access same reports!**

No need to copy files - everything is in the cloud!

---

## 🐛 Troubleshooting

### Tests Fail?

```bash
# Check specific component
python test_setup.py

# Common fixes:
# - Environment variables: Check .env file
# - Database: Verify Supabase tables created
# - Storage: Verify buckets created
# - Ollama: Run 'ollama list' to check models
```

### Need More Help?

- **Detailed Setup**: See [INSTALL.md](INSTALL.md)
- **Configuration**: See [README.md](README.md)
- **Supabase Issues**: Check [Supabase Dashboard](https://app.supabase.com)

---

## 🎉 Success!

You've set up a production-ready, cloud-backed PPE safety monitoring system!

**Key Benefits:**

- 🌐 **Multi-device access** - View reports from anywhere
- ☁️ **Cloud storage** - No disk space limits
- 🔐 **Secure** - Private buckets with signed URLs
- 📈 **Scalable** - Postgres handles growth
- 💾 **Backed up** - Supabase handles backups

---

**🌙 LUNA Supabase Edition - Happy Monitoring!**
