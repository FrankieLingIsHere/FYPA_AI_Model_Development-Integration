"""
Camera Diagnostic Script for PPE Pipeline
Troubleshoots the MSMF video capture error on Windows.
"""
import cv2
import sys

def test_camera_backends():
    """Test different OpenCV backends for camera capture."""
    print("=" * 60)
    print("Camera Diagnostic Tool")
    print("=" * 60)
    
    # Print OpenCV version and build info
    print(f"\nOpenCV Version: {cv2.__version__}")
    print(f"Build Info (video I/O backends):")
    build_info = cv2.getBuildInformation()
    for line in build_info.split('\n'):
        if 'Video I/O' in line or 'MSMF' in line or 'DirectShow' in line or 'FFMPEG' in line:
            print(f"  {line.strip()}")
    
    # List of backends to try on Windows
    backends = [
        (cv2.CAP_DSHOW, "DirectShow (CAP_DSHOW)"),
        (cv2.CAP_MSMF, "Microsoft Media Foundation (CAP_MSMF)"),
        (cv2.CAP_ANY, "Auto-detect (CAP_ANY)"),
    ]
    
    print("\n" + "=" * 60)
    print("Testing Camera Backends...")
    print("=" * 60)
    
    working_backend = None
    
    for backend_id, backend_name in backends:
        print(f"\n[TEST] {backend_name}...")
        try:
            cap = cv2.VideoCapture(0, backend_id)
            
            if not cap.isOpened():
                print(f"  ❌ Failed to open camera with {backend_name}")
                continue
            
            # Try to read a few frames
            success_count = 0
            for i in range(5):
                ret, frame = cap.read()
                if ret and frame is not None:
                    success_count += 1
            
            cap.release()
            
            if success_count >= 3:
                print(f"  ✅ SUCCESS: {backend_name} - Read {success_count}/5 frames")
                if working_backend is None:
                    working_backend = (backend_id, backend_name)
            else:
                print(f"  ⚠️ PARTIAL: {backend_name} - Only read {success_count}/5 frames")
                
        except Exception as e:
            print(f"  ❌ ERROR: {backend_name} - {e}")
    
    print("\n" + "=" * 60)
    print("Diagnosis Complete")
    print("=" * 60)
    
    if working_backend:
        backend_id, backend_name = working_backend
        print(f"\n✅ Recommended backend: {backend_name}")
        print(f"\nTo fix your code, change:")
        print(f"  FROM: cap = cv2.VideoCapture(0)")
        print(f"  TO:   cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)")
        return backend_id
    else:
        print("\n❌ No working backend found!")
        print("\nPossible causes:")
        print("  1. Camera is being used by another application")
        print("  2. Camera drivers need updating")
        print("  3. Camera permissions not granted in Windows Settings")
        print("  4. No camera connected")
        print("\nTry:")
        print("  - Close other apps using the camera (Zoom, Teams, etc.)")
        print("  - Check Windows Settings > Privacy > Camera")
        print("  - Update camera drivers")
        return None


def test_with_directshow():
    """Test camera with DirectShow backend (usually works better on Windows)."""
    print("\n" + "=" * 60)
    print("Testing Live Feed with DirectShow...")
    print("=" * 60)
    
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    
    if not cap.isOpened():
        print("❌ Could not open camera with DirectShow")
        return False
    
    # Set some properties that help with stability
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    
    print("✅ Camera opened successfully!")
    print("Press 'q' to quit the test...")
    
    frame_count = 0
    error_count = 0
    
    while True:
        ret, frame = cap.read()
        
        if not ret:
            error_count += 1
            if error_count > 10:
                print(f"Too many frame errors ({error_count}), stopping...")
                break
            continue
        
        error_count = 0  # Reset on successful read
        frame_count += 1
        
        # Add frame counter to display
        cv2.putText(frame, f"Frame: {frame_count}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        cv2.imshow('Camera Test (DirectShow)', frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()
    print(f"\nTotal frames captured: {frame_count}")
    return True


if __name__ == "__main__":
    # Run diagnostics first
    best_backend = test_camera_backends()
    
    if best_backend is not None:
        response = input("\nWould you like to test the live feed? (y/n): ")
        if response.lower() == 'y':
            test_with_directshow()
