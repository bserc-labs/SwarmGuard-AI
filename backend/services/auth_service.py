from datetime import UTC, datetime, timedelta

# PyJWT, not python-jose. python-jose pulled in `ecdsa`, whose advisory
# PYSEC-2026-1325 has no fixed version -- its maintainers treat side
# channels as out of scope -- and it was the one finding that kept the
# dependency audit from becoming a gate. The tokens are the same HS256 JWTs
# either library writes, so sessions issued before the switch stay valid.
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from passlib.context import CryptContext

from config import get_settings

settings = get_settings()

SECRET_KEY = settings.SECRET_KEY
if not SECRET_KEY:
    raise RuntimeError("CRITICAL: SECRET_KEY environment variable is not set. Cannot start securely.")

# Signing always uses SECRET_KEY. Verifying tries it first and then the key it
# replaced, so a rotation does not log every user out at the same instant --
# see SECRET_KEY_PREVIOUS in config.py.
VERIFICATION_KEYS: tuple[str, ...] = tuple(
    key for key in (SECRET_KEY, settings.SECRET_KEY_PREVIOUS) if key
)

ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> dict | None:
    for key in VERIFICATION_KEYS:
        try:
            return jwt.decode(token, key, algorithms=[ALGORITHM])
        except ExpiredSignatureError:
            # The signature verified with this key; the token is simply too old.
            # No other key can make it valid.
            return None
        except InvalidTokenError:
            continue
    return None
