import os
import sys
import time
import uuid
import json
import requests
from pathlib import Path

def generate_machine_id():
    """Generate or retrieve a persistent machine ID for this edge node."""
    id_file = Path('machine_id.txt')
    if id_file.exists():
        with open(id_file, 'r') as f:
            return f.read().strip()
    
    # Generate a stronger machine ID namespace to reduce accidental collisions.
    new_id = f"Edge-{uuid.uuid4().hex[:12].upper()}"
    with open(id_file, 'w') as f:
        f.write(new_id)
    return new_id

def main():
    print("=" * 60)
    print(" LUNA Edge Node Provisioning ".center(60, '='))
    print("=" * 60)
    
    # Get cluster URL from environment or prompt if missing
    cloud_url = os.getenv('CLOUD_URL', '').strip()
    if not cloud_url:
        print("ERROR: CLOUD_URL is not set.")
        print("Please set CLOUD_URL in the start.bat file to point to your cloud dashboard.")
        sys.exit(1)
        
    # Standardize URL
    if not cloud_url.startswith('http'):
        cloud_url = f"https://{cloud_url}"
    cloud_url = cloud_url.rstrip('/')
        
    machine_id = generate_machine_id()
    
    request_endpoint = f"{cloud_url}/api/provision/request"
    status_endpoint = f"{cloud_url}/api/provision/status"
    exchange_endpoint = f"{cloud_url}/api/provision/bootstrap-exchange"
    
    print(f"[*] Generated Machine ID: {machine_id}")
    print(f"[*] Requesting permission to join cluster at {cloud_url}...")
    
    # Send provisioning request
    try:
        resp = requests.post(
            request_endpoint, 
            json={"machine_id": machine_id},
            timeout=10
        )
        resp.raise_for_status()
        request_data = resp.json()
    except requests.exceptions.RequestException as e:
        print(f"\n[!] Failed to connect to Cloud Dashboard:")
        print(f"    {e}")
        print("\nEnsure the Cloud Dashboard is running and accessible.")
        sys.exit(1)

    provision_secret = str((request_data or {}).get('provision_secret') or '').strip()
    if not provision_secret:
        print("\n[!] Cloud response did not include provision_secret.")
        print("    Cannot proceed with secure polling.")
        sys.exit(1)
        
    print("\n" + "="*60)
    print(" ACTION REQUIRED ".center(60))
    print("="*60)
    print(f"\nYour administrator must approve this edge node.")
    print(f"\nPlease ask them to visit:")
    print(f"  👉  {cloud_url}/admin/devices")
    print(f"\nAnd approve Machine ID:  [ {machine_id} ]")
    print("\nWaiting for approval...")
    print("(This screen will automatically continue once approved)\n")
    
    # Polling loop
    poll_interval = 5  # seconds
    max_retries = 120  # 10 minutes total
    
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                status_endpoint, 
                params={
                    "machine_id": machine_id,
                    "provision_secret": provision_secret,
                },
                timeout=5
            )
            
            if resp.status_code == 200:
                data = resp.json()
                status = data.get('status')
                
                if status in ('approved', 'provisioned'):
                    print("\n[OK] SUCCESS: Device approved by administrator!")
                    bootstrap_token = str(data.get('bootstrap_token') or '').strip()
                    if not bootstrap_token:
                        print("[!] Missing bootstrap token in status response.")
                        sys.exit(1)

                    # Exchange one-time bootstrap token for credentials.
                    exchange_resp = requests.post(
                        exchange_endpoint,
                        json={
                            "machine_id": machine_id,
                            "provision_secret": provision_secret,
                            "bootstrap_token": bootstrap_token,
                        },
                        timeout=10,
                    )
                    exchange_resp.raise_for_status()
                    exchange_data = exchange_resp.json()
                    credentials = exchange_data.get('credentials', {})

                    # Write .env securely
                    with open('.env', 'w') as f:
                        f.write(f"SUPABASE_URL={credentials.get('SUPABASE_URL', '')}\n")
                        f.write(f"SUPABASE_SERVICE_ROLE_KEY={credentials.get('SUPABASE_SERVICE_ROLE_KEY', '')}\n")
                        f.write(f"SUPABASE_DB_URL={credentials.get('SUPABASE_DB_URL', '')}\n")

                        # Add some safe defaults
                        f.write("\n# Safe Defaults for Edge Node\n")
                        f.write("FLASK_DEBUG=false\n")
                        f.write("SERVE_FRONTEND=false\n") # Edge nodes usually don't need UI
                        f.write("UPLOAD_PDF=false\n")

                    print("[*] Credentials securely written to .env")
                    print("[*] Provisioning complete. Starting pipeline...\n")
                    time.sleep(2)
                    sys.exit(0)
                    
                elif status == 'pending':
                    print(".", end="", flush=True)
                else:
                    print(f"\n[!] Unexpected status: {status}")
            
            elif resp.status_code == 404:
                print("\n[!] Request was rejected or deleted by administrator.")
                sys.exit(1)
                
        except requests.exceptions.RequestException:
            print("x", end="", flush=True)  # Indicator of network blip
            
        time.sleep(poll_interval)
        
    print("\n\n[!] Timed out waiting for approval (10 minutes).")
    print("Please restart start.bat to try again.")
    sys.exit(1)

if __name__ == '__main__':
    main()
