
import requests
import time

REPORT_ID = "20260210_155220"
API_URL = f"http://localhost:5000/api/report/{REPORT_ID}/reprocess"

print(f"Triggering reprocessing for {REPORT_ID}...")
try:
    response = requests.post(API_URL)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.ok:
        print("Reprocessing queued successfully.")
    else:
        print("Failed to queue reprocessing.")

except Exception as e:
    print(f"Error connecting to API: {e}")
    print("Ensure the app is running (start.bat).")
