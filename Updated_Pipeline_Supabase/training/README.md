# Training Assets

This directory is the tracked home for model-training materials that support the CASM pipeline but are not part of the deployed runtime.

## Layout

- `notebooks/`
  - Colab-friendly experiments, training runs, and export workflows

## Current Notebook

- `notebooks/YOLO26_PPE_11CLS_Training.ipynb`
  - Two-phase YOLO26 PPE detector training notebook
  - Uses Google Colab + Google Drive paths for dataset staging and result export
  - Covers dataset prep, training, resume, monitoring, evaluation, and model export

## Notes

- These assets are for experimentation and reproducibility, not for app startup.
- Runtime inference still uses the exported model weights configured elsewhere in the pipeline.
- If more notebooks are added later, keep them under `training/notebooks/` rather than creating new ad hoc folders.
