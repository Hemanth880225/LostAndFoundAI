
import os
from pathlib import Path

# Base Paths
ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = ROOT_DIR / "app"
UPLOADS_DIR = ROOT_DIR / "uploads"

# Safe Handover & Location Provider Settings
NOMINATIM_BASE_URL = os.getenv(
    "NOMINATIM_BASE_URL",
    "https://nominatim.openstreetmap.org"
)
OVERPASS_BASE_URL = os.getenv(
    "OVERPASS_BASE_URL",
    "https://overpass-api.de/api/interpreter"
)
LOCATION_PROVIDER_USER_AGENT = os.getenv(
    "LOCATION_PROVIDER_USER_AGENT",
    "LostAndFoundAI/1.0 (contact: admin@lostandfound.local)"
)
LOCATION_REQUEST_TIMEOUT = float(os.getenv("LOCATION_REQUEST_TIMEOUT", "10.0"))
LOCATION_CACHE_TTL_SECONDS = int(os.getenv("LOCATION_CACHE_TTL_SECONDS", "300"))

# College Campus Handover Configuration
CAMPUS_NAME = os.getenv("CAMPUS_NAME", "College Security & Lost Property Desk")
CAMPUS_LATITUDE = float(os.getenv("CAMPUS_LATITUDE", "18.5204"))
CAMPUS_LONGITUDE = float(os.getenv("CAMPUS_LONGITUDE", "73.8567"))
CAMPUS_ADDRESS = os.getenv("CAMPUS_ADDRESS", "Main Campus Administrative Complex, Ground Floor, Security Command Desk")
CAMPUS_CITY = os.getenv("CAMPUS_CITY", "Pune")
CAMPUS_PHONE = os.getenv("CAMPUS_PHONE", "+91 20 2569 0000")
CAMPUS_HOURS = os.getenv("CAMPUS_HOURS", "24/7 (Always Open)")
CAMPUS_RADIUS_KM = float(os.getenv("CAMPUS_RADIUS_KM", "5.0"))

# Verified Claims & Private Evidence Settings
PRIVATE_EVIDENCE_DIR = ROOT_DIR / "uploads" / "private_evidence"
MAX_EVIDENCE_FILE_SIZE_BYTES = int(os.getenv("MAX_EVIDENCE_FILE_SIZE_BYTES", "5242880"))  # 5 MiB
ALLOWED_EVIDENCE_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}

# Value-Based Reward Points Policy (5 points = ₹1)
POINTS_PER_RUPEE = int(os.getenv("POINTS_PER_RUPEE", "5"))
DEFAULT_REWARD_RATE = float(os.getenv("DEFAULT_REWARD_RATE", "0.10"))  # 10%
MIN_REWARD_RUPEES = float(os.getenv("MIN_REWARD_RUPEES", "50.0"))
MAX_REWARD_RUPEES = float(os.getenv("MAX_REWARD_RUPEES", "2000.0"))
MAX_UNVERIFIED_VALUE_CAP = float(os.getenv("MAX_UNVERIFIED_VALUE_CAP", "500.0"))
