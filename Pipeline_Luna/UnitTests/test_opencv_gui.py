"""Quick OpenCV GUI Test"""
import cv2
import numpy as np

print("Testing OpenCV GUI...")
print(f"OpenCV version: {cv2.__version__}")

# Create a test image
img = np.zeros((300, 400, 3), dtype=np.uint8)
cv2.putText(img, "OpenCV GUI Test", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

try:
    cv2.imshow("Test Window", img)
    print("[OK] cv2.imshow() works!")
    
    print("Press any key to close...")
    cv2.waitKey(2000)  # Wait 2 seconds or key press
    cv2.destroyAllWindows()
    print("[OK] cv2.waitKey() and cv2.destroyAllWindows() work!")
    print("\n[SUCCESS] OpenCV GUI is fully functional!")
    
except cv2.error as e:
    print(f"[ERROR] OpenCV GUI error: {e}")
    print("OpenCV GUI is NOT available")
