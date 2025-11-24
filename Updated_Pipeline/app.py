"""
Flask web app for PPE compliance demo: live webcam annotation and image upload inference.

Endpoints:
- /            : Home page with links to live and upload
- /live        : Streams live webcam frames with annotation
- /upload      : Accepts image upload, returns annotated image and detections

Requires: infer_image.py, live_ppe_compliance.py, ultralytics, opencv-python, flask, pillow
"""

import os
import sys
from flask import Flask, render_template_string, request, Response, jsonify
import cv2
import numpy as np
from infer_image import predict_image
from threading import Thread
from PIL import Image
import io
import base64

app = Flask(__name__)

# Home page: links to live and upload
HOME_HTML = '''
<!DOCTYPE html>
<html><head><title>PPE Compliance Demo</title>
<style>
body { font-family: Arial, sans-serif; background: #f7f7f7; }
.container { max-width: 900px; margin: 40px auto; background: #fff; padding: 32px; border-radius: 12px; box-shadow: 0 2px 8px #ccc; }
h2 { color: #2c3e50; }
.btn { display: inline-block; margin: 12px 0; padding: 10px 24px; background: #3498db; color: #fff; border-radius: 6px; text-decoration: none; font-size: 18px; }
.btn:hover { background: #217dbb; }
</style>
</head>
<body>
<div class="container">
<h2>PPE Compliance Demo</h2>
<a class="btn" href="/live">Live Webcam Annotation</a>
<a class="btn" href="/upload">Image Upload Inference</a>
</div>
</body></html>
'''

@app.route('/')
def home():
    return render_template_string(HOME_HTML)

# --- Live webcam streaming ---
def gen_live_frames(conf=0.10, model_path=None):
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError('Could not open webcam')
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        # Run inference and annotate
        dets, annotated = predict_image(frame, model_path=model_path, conf=conf)
        # Encode as JPEG for streaming
        ret2, jpeg = cv2.imencode('.jpg', annotated)
        if not ret2:
            continue
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
    cap.release()

LIVE_HTML = '''
<!DOCTYPE html>
<html><head><title>Live Webcam Annotation</title>
<style>
body { font-family: Arial, sans-serif; background: #f7f7f7; }
.container { max-width: 900px; margin: 40px auto; background: #fff; padding: 32px; border-radius: 12px; box-shadow: 0 2px 8px #ccc; }
h3 { color: #2c3e50; }
img { border-radius: 8px; box-shadow: 0 1px 4px #aaa; }
.btn { display: inline-block; margin: 18px 0; padding: 10px 24px; background: #3498db; color: #fff; border-radius: 6px; text-decoration: none; font-size: 18px; }
.btn:hover { background: #217dbb; }
</style>
</head>
<body>
<div class="container">
<h3>Live Webcam Annotation</h3>
<img src="/video_feed" width="800" />
<br><a class="btn" href="/">Back to Home</a>
</div>
</body></html>
'''

@app.route('/live')
def live():
    return render_template_string(LIVE_HTML)

@app.route('/video_feed')
def video_feed():
    return Response(gen_live_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- Image upload inference ---
UPLOAD_HTML = '''
<!DOCTYPE html>
<html><head><title>Image Upload Inference</title>
<style>
body { font-family: Arial, sans-serif; background: #f7f7f7; }
.container { max-width: 900px; margin: 40px auto; background: #fff; padding: 32px; border-radius: 12px; box-shadow: 0 2px 8px #ccc; }
h3 { color: #2c3e50; }
input[type=file] { font-size: 18px; margin: 12px 0; }
.btn { display: inline-block; margin: 12px 0; padding: 10px 24px; background: #3498db; color: #fff; border-radius: 6px; text-decoration: none; font-size: 18px; }
.btn:hover { background: #217dbb; }
img { border-radius: 8px; box-shadow: 0 1px 4px #aaa; margin-top: 18px; }
pre { background: #f4f4f4; padding: 12px; border-radius: 8px; }
</style>
</head>
<body>
<div class="container">
<h3>Image Upload Inference</h3>
<form method="POST" enctype="multipart/form-data">
  <input type="file" name="image" accept="image/*" required />
  <input class="btn" type="submit" value="Run Inference" />
</form>
{% if result_img %}
  <h4>Annotated Image:</h4>
  <img src="data:image/jpeg;base64,{{ result_img }}" width="800" />
  <h4>Detections:</h4>
  <pre>{{ detections }}</pre>
{% endif %}
<br><a class="btn" href="/">Back to Home</a>
</div>
</body></html>
'''

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    result_img = None
    detections = None
    if request.method == 'POST':
        if 'image' not in request.files:
            return 'No image uploaded', 400
        file = request.files['image']
        img_bytes = file.read()
        dets, annotated = predict_image(img_bytes)
        # Encode annotated image to base64
        _, buffer = cv2.imencode('.jpg', annotated)
        result_img = base64.b64encode(buffer).decode('utf-8')
        detections = '\n'.join([str(d) for d in dets])
    return render_template_string(UPLOAD_HTML, result_img=result_img, detections=detections)

if __name__ == '__main__':
    app.run(debug=True)
