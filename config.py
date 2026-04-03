# ─────────────────────────────────────────────
#  Business Blastar — Configuration / Credentials
# ─────────────────────────────────────────────
import os

# Flask
SECRET_KEY = "business_blastar_secret_key"

# MongoDB
MONGO_URI = "mongodb://localhost:27017/"
DATABASE_NAME = "Business_Blastar"
COLLECTION_NAME = "business"
COUNTERS_COLLECTION = "counters"

# Images directory  (shared across versions)
IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Images"
)

# Allowed image extensions
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg", "webp"}
