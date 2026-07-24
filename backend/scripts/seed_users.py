import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import logger
import sys
import os
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from database import SessionLocal, engine, Base
import models
from services.auth_service import get_password_hash

def seed_users():
    # Create all tables first
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    # Check if admin already exists
    admin = db.query(models.User).filter(models.User.username == "admin").first()
    if admin:
        logger.info("✅ Admin user already exists!")
        return
        
    # Create new admin user
    hashed_password = get_password_hash("admin")
    new_user = models.User(
        username="admin",
        email="admin@swarmguard.ai",
        password=hashed_password,
        role="ADMIN"
    )
    
    db.add(new_user)
    db.commit()
    logger.info("✅ Admin user created successfully (username: 'admin', password: 'admin')")
    
    db.close()

if __name__ == "__main__":
    seed_users()
