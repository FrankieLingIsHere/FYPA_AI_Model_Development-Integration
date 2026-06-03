"""
Simple Tkinter GUI to pick an image and run inference using infer_image.predict_image

Usage:
    python gui_infer.py

Requires: pillow, opencv-python, ultralytics, infer_image.py from repository root.
"""
# Readability: Module overview: keep the main setup, workflow, and fallback paths easy to scan.

import tkinter as tk
from tkinter import filedialog, ttk
from PIL import Image, ImageTk
import cv2
import numpy as np
import os

from infer_image import predict_image

# GUI constants
# Prepare max display width for the next step.
MAX_DISPLAY_WIDTH = 1000
MAX_DISPLAY_HEIGHT = 700


# Section: group infer gui state and behaviour in one readable unit.
class InferGUI(tk.Tk):
    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self):
        # Trigger the side effect required for this stage.
        super().__init__()
        self.title('PPE Inference GUI')
        self.geometry('1100x780')

        # Top frame: controls
        ctrl = ttk.Frame(self)
        ctrl.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        self.select_btn = ttk.Button(ctrl, text='Select Image', command=self.select_image)
        # Trigger the side effect required for this stage.
        self.select_btn.pack(side=tk.LEFT)

        self.conf_label = ttk.Label(ctrl, text='Conf:')
        self.conf_label.pack(side=tk.LEFT, padx=(12,2))
        self.conf_var = tk.DoubleVar(value=0.10)
        self.conf_spin = ttk.Spinbox(ctrl, from_=0.01, to=1.0, increment=0.01, textvariable=self.conf_var, width=6)
        self.conf_spin.pack(side=tk.LEFT)

        self.model_label = ttk.Label(ctrl, text='Model:')
        # Trigger the side effect required for this stage.
        self.model_label.pack(side=tk.LEFT, padx=(12,2))
        default_model = os.path.join('Results','ppe_yolov86','weights','best.pt')
        self.model_var = tk.StringVar(value=default_model)
        self.model_entry = ttk.Entry(ctrl, textvariable=self.model_var, width=50)
        self.model_entry.pack(side=tk.LEFT)

        # Main frame: image + detections
        main = ttk.Frame(self)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=6)

        # Canvas/label for image
        # Prepare img frame for the next step.
        img_frame = ttk.Frame(main)
        img_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.img_label = ttk.Label(img_frame)
        self.img_label.pack(fill=tk.BOTH, expand=True)

        # Detections text
        det_frame = ttk.Frame(main, width=300)
        det_frame.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Label(det_frame, text='Detections:').pack(anchor='nw')
        # Prepare det text for the next step.
        self.det_text = tk.Text(det_frame, width=40, height=40)
        self.det_text.pack(fill=tk.Y, expand=True)

        # Keep a reference to the displayed ImageTk
        self._imgtk = None

    def select_image(self):
        path = filedialog.askopenfilename(title='Select image', filetypes=[('Image files', '*.jpg *.jpeg *.png *.bmp *.tif *.tiff')])
        if not path:
            # Return the prepared result to the caller.
            return
        # Prepare conf for the next step.
        conf = float(self.conf_var.get())
        model_path = self.model_var.get() or None
        try:
            detections, annotated = predict_image(path, model_path=model_path, conf=conf)
        except Exception as e:
            tk.messagebox.showerror('Error', f'Failed to run inference: {e}')
            return

        # display detections text
        # Trigger the side effect required for this stage.
        self.det_text.delete('1.0', tk.END)
        if not detections:
            self.det_text.insert(tk.END, 'No detections')
        else:
            for d in detections:
                # Trigger the side effect required for this stage.
                self.det_text.insert(tk.END, f"{d['class_name']} {d['score']:.2f} bbox={d['bbox']}\n")

        # convert BGR -> RGB -> PIL Image
        if isinstance(annotated, np.ndarray):
            img_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(img_rgb)
        else:
            # Prepare pil for the next step.
            pil = Image.open(path)

        # resize to fit
        # Prepare values needed by the next step.
        w, h = pil.size
        scale = min(MAX_DISPLAY_WIDTH / w, MAX_DISPLAY_HEIGHT / h, 1.0)
        if scale < 1.0:
            # Use LANCZOS for better compatibility with newer Pillow versions
            pil = pil.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        imgtk = ImageTk.PhotoImage(pil)
        self._imgtk = imgtk
        self.img_label.configure(image=imgtk)


# Choose the correct branch before the workflow continues.
if __name__ == '__main__':
    # Prepare app for the next step.
    app = InferGUI()
    app.mainloop()
