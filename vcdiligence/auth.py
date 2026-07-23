from fastapi import Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from typing import Optional
from vcdiligence.database import get_db, User, Organization
from vcdiligence.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    token_query: Optional[str] = Query(None, alias="token"),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Extract token either from headers or from query params (needed for browser direct PDF download link)
    actual_token = token or token_query
    if not actual_token:
        raise credentials_exception

    payload = decode_access_token(actual_token)
    if payload is None:
        raise credentials_exception

    email: str = payload.get("sub")
    if email is None:
        raise credentials_exception

    user = db.query(User).filter_by(email=email).first()
    if user is None:
        raise credentials_exception
    return user

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "administrador":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation restricted to administrator role only"
        )
    return current_user
