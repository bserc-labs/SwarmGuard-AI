from database import SessionLocal
from models import User
from services.auth_service import get_password_hash

db = SessionLocal()

username = "admin"
email = "admin@swarmguard.ai"
password = "admin123"

existing = db.query(User).filter(User.username == username).first()

if existing:
    print("Admin already exists!")
else:
    admin = User(
        username=username,
        email=email,
        password=get_password_hash(password),
        role="admin"
    )
    db.add(admin)
    db.commit()
    print("Admin created successfully!")

db.close()