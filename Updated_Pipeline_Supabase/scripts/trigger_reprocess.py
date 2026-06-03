# Readability: Utility script: keep operational maintenance steps visible and repeatable.

import requests
import time

# Prepare report id for the next step.
REPORT_ID = "20260210_155220"
API_URL = f"http://localhost:5000/api/report/{REPORT_ID}/reprocess"

print(f"Triggering reprocessing for {REPORT_ID}...")
try:
    # Prepare response for the next step.
    response = requests.post(API_URL)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.ok:
        # Trigger the side effect required for this stage.
        print("Reprocessing queued successfully.")
    else:
        print("Failed to queue reprocessing.")

except Exception as e:
    # Trigger the side effect required for this stage.
    print(f"Error connecting to API: {e}")
    print("Ensure the app is running (start.bat).")
