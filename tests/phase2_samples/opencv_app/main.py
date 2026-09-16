import cv2
import numpy as np

image = np.zeros((120, 240, 3), dtype=np.uint8)
cv2.putText(image, "Phase 2 OK", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
print("opencv", cv2.__version__, "shape", image.shape)
