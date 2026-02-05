import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/yar.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", f"{BASE_DIR}/uploads")
