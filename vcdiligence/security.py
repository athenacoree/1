import os
import datetime
from typing import Union, Any
import jwt
import bcrypt

# Secret keys and algorithm
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-dealscout-key-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480 # 8 hours

def hash_password(password: str) -> str:
    # Hash password using bcrypt directly
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: Union[datetime.timedelta, None] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire.timestamp()}) # PyJWT uses timestamp
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)

def decode_access_token(token: str) -> Union[dict, None]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except Exception:
        return None
