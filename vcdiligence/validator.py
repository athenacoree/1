import socket
import ipaddress
from urllib.parse import urlparse
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
import datetime
from vcdiligence.database import AuditLog

def validate_url_for_ssrf(url: str) -> str:
    """
    Validates that a URL is a valid http/https URL and resolves to a public, non-private IP address.
    Raises HTTPException if invalid.
    """
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid URL structure: {str(e)}"
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL is missing a valid hostname."
        )

    # Resolve hostname to IP address
    try:
        ips = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not resolve hostname: {hostname}"
        )

    for item in ips:
        ip_str = item[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            # Check for loopback, private, link-local, reserved, multicast, or unspecified IP
            if (ip_obj.is_private or
                ip_obj.is_loopback or
                ip_obj.is_link_local or
                ip_obj.is_multicast or
                ip_obj.is_reserved or
                ip_obj.is_unspecified or
                ip_str == "0.0.0.0" or
                ip_str == "::" or
                ip_str.startswith("127.") or
                ip_str.startswith("10.") or
                ip_str.startswith("192.168.") or
                ip_str.startswith("172.1") or ip_str.startswith("172.2") or ip_str.startswith("172.3")
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Access to private or local IP address is prohibited: {ip_str}"
                )
        except ValueError:
            # If for some reason it's not a valid IP string format
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Resolved host has invalid IP: {ip_str}"
            )

    return url

def check_rate_limit(organization_id: int, db: Session, limit: int = 5, window_minutes: int = 60):
    """
    Checks the rate limit for the given organization_id based on recent AuditLogs.
    Raises HTTPException if limit exceeded.
    """
    since_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=window_minutes)
    count = db.query(func.count(AuditLog.id)).filter(
        AuditLog.organization_id == organization_id,
        AuditLog.action == "analyze_startup",
        AuditLog.timestamp >= since_time
    ).scalar()

    if count >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Maximum {limit} analyses per {window_minutes} minutes."
        )
