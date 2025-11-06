# 🚀 Quick Start Guide

Get up and running in 10 minutes!

## ⚡ TL;DR - Fastest Setup

```cmd
# 1. Clone repo
git clone https://github.com/yourusername/ppe-safety-monitor.git
cd ppe-safety-monitor

# 2. Run setup (installs everything except Llama 3)
setup.bat

# 3. Download Llama 3 (requires HuggingFace access)
huggingface-cli login
python download_llama3.py

# 4. Run live demo
python run_live_demo.py
```

## 📋 Prerequisites Checklist

Before starting, make sure you have:

- ✅ **Python 3.10+** - [Download](https://www.python.org/downloads/)
- ✅ **NVIDIA GPU with 8GB+ VRAM** - RTX 3060 or better
- ✅ **NVIDIA Drivers** - [Download](https://www.nvidia.com/download/index.aspx)
- ✅ **50GB+ free disk space** - For models and dataset
- ✅ **Stable internet** - For downloading models (~20GB total)

## 🎯 Step-by-Step Setup

### Step 1: Python Installation

**Download Python 3.11:**
- Visit: https://www.python.org/downloads/
- Download Python 3.11 (recommended)
- ⚠️ **IMPORTANT**: Check "Add Python to PATH" during installation!

**Verify installation:**
```cmd
python --version
```
Expected output: `Python 3.11.x` or `Python 3.10.x`

### Step 2: Clone Repository

```cmd
git clone https://github.com/yourusername/ppe-safety-monitor.git
cd ppe-safety-monitor
```

Or download ZIP:
- Click "Code" → "Download ZIP"
- Extract to your preferred location

### Step 3: Run Automated Setup

**Windows:**
```cmd
setup.bat
```

This will:
1. ✅ Check Python and GPU
2. ✅ Create virtual environment
3. ✅ Install PyTorch with CUDA
4. ✅ Install all dependencies
5. ✅ Download LLaVA model
6. ✅ Create necessary directories

**Estimated time**: 15-20 minutes (depending on internet speed)

### Step 4: Setup Llama 3 Model

⚠️ **This requires a HuggingFace account**

**Option A: Automatic Download (Recommended)**

1. **Get HuggingFace access:**
   - Visit: https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct
   - Click "Request Access"
   - Usually approved instantly

2. **Login to HuggingFace:**
   ```cmd
   pip install huggingface_hub
   huggingface-cli login
   ```
   - Get token from: https://huggingface.co/settings/tokens
   - Paste when prompted

3. **Download model:**
   ```cmd
   python download_llama3.py
   ```
   - Downloads ~15GB
   - Takes 10-20 minutes

**Option B: Use Ollama (Simpler but uses more RAM)**

1. **Install Ollama:**
   - Download from: https://ollama.ai
   - Run installer

2. **Pull Llama 3:**
   ```cmd
   ollama pull llama3
   ```

3. **Start Ollama:**
   ```cmd
   ollama serve
   ```

System will automatically use Ollama if local model not found.

### Step 5: Verify Installation

```cmd
python test_gpu_optimized.py
```

**Expected output:**
```
✅ GPU: NVIDIA GeForce RTX XXXX
✅ Model loaded: ~6.3 GB used
⏱️  Time: ~80 seconds
✅ JSON Generated Successfully!
```

If you see errors, check [Troubleshooting](#troubleshooting).

## 🎮 Running the System

### Live PPE Monitoring

**Start live demo:**
```cmd
python run_live_demo.py
```

Or double-click:
```
run_live_ppe.bat
```

**What to expect:**
- Webcam opens
- YOLO detects PPE in real-time
- Violations trigger automatic reporting
- Press `q` to quit

**First violation takes ~2 minutes:**
- 20s: Model loading (one-time)
- 3s: Image captioning
- 90s: NLP analysis
- Report saved to `pipeline/violations/`

### View Reports

**Start web server:**
```cmd
python view_reports.py
```

Or double-click:
```
run_report_viewer.bat
```

**Then visit:**
```
http://localhost:5001
```

**Features:**
- 📊 Dashboard with statistics
- 📁 Browse all violation reports
- 📈 Analytics and trends
- 🔍 Search and filter

## 📦 Optional: Dataset Setup

Only needed for training new models.

**Download:**
1. Visit: https://www.kaggle.com/datasets/shlokraval/ppe-dataset-yolov8
2. Download dataset (~5GB)
3. Extract to `data/` folder

**Expected structure:**
```
data/
├── data.yaml
├── train/
│   ├── images/
│   └── labels/
├── valid/
│   ├── images/
│   └── labels/
└── test/
    ├── images/
    └── labels/
```

## 🐛 Troubleshooting

### Issue: "Python not found"
**Solution:**
- Install Python 3.10+
- Make sure "Add to PATH" was checked
- Restart terminal

### Issue: "CUDA not available"
**Solution:**
```cmd
# Check GPU
nvidia-smi

# Reinstall PyTorch
pip uninstall torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

### Issue: "No access to Llama 3"
**Solution:**
- Request access: https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct
- Wait for approval (usually instant)
- Or use Ollama alternative

### Issue: "Out of memory"
**Solution:**
- Close other applications
- GPU must have 8GB+ VRAM
- Check: `nvidia-smi`

### Issue: "Webcam not found"
**Solution:**
Edit `pipeline/backend/core/yolo_stream.py`:
```python
cap = cv2.VideoCapture(0)  # Change 0 to 1, 2, etc.
```

## 📚 Next Steps

1. **Read full documentation:** `README.md`
2. **Configure settings:** `pipeline/config.py`
3. **Explore web interface:** http://localhost:5001
4. **Test with images:** `python infer_image.py --image test.jpg`

## 🆘 Getting Help

- **Documentation:** README.md
- **Issues:** [GitHub Issues](https://github.com/yourusername/ppe-safety-monitor/issues)
- **Discussions:** [GitHub Discussions](https://github.com/yourusername/ppe-safety-monitor/discussions)

## ⏱️ Time Estimates

| Task | Time |
|------|------|
| Python installation | 5 min |
| Clone repository | 1 min |
| Run setup.bat | 15-20 min |
| Download Llama 3 | 10-20 min |
| Verify installation | 2 min |
| **Total** | **~40 min** |

## ✅ Success Checklist

Before running live demo:

- [ ] Python 3.10+ installed
- [ ] GPU detected (nvidia-smi works)
- [ ] Virtual environment created
- [ ] PyTorch with CUDA installed
- [ ] All dependencies installed
- [ ] LLaVA model downloaded
- [ ] Llama 3 model downloaded OR Ollama running
- [ ] test_gpu_optimized.py passes

---

**Ready to go? Start with:** `python run_live_demo.py`

🎉 **Happy monitoring!**
