from database import SessionLocal
from models import User
from services.auth_service import get_password_hash

db = SessionLocal()
admin = db.query(User).filter(User.username == "admin").first()
if admin:
    admin.password = get_password_hash("admin123")
    db.commit()
    print("Password reset to admin123")
else:
    print("Admin not found")
