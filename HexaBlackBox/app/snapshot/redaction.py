import re

# Comprehensive list of regex patterns for redaction
_REDACTION_PATTERNS = [
    # Standalone JWTs (header.payload.signature)
    (r"\beyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\b", "<REDACTED_JWT>"),
    
    # Authorization headers (e.g. Authorization: Bearer ...)
    (r"(?i)(authorization:\s*)(?:bearer\s+)?[a-z0-9_\-\.\~]+", r"\1<REDACTED_TOKEN>"),
    
    # Token query parameters (token, access_token, refresh_token, id_token)
    (r"(?i)(\b(?:token|access_token|refresh_token|id_token)=)[a-z0-9_\-\.\~]+", r"\1<REDACTED>"),
    
    # Cookies / Set-Cookie headers
    (r"(?i)(\b(?:cookie|set-cookie):\s*)[^\r\n]+", r"\1<REDACTED>"),
    
    # Password and Secret fields in JSON, query, or command lines
    (r'(?i)(\b(?:password|secret|api_key|apikey)["\']?\s*[:=]\s*["\']?)[^"\'\r\n,\}]+', r"\1<REDACTED>"),
    
    # Database Connection Strings (e.g. postgresql://user:pass@host)
    (r"([a-zA-Z0-9\+]+://)[^:@\r\n]+:[^@\r\n]+@([a-zA-Z0-9_\-\.]+)", r"\1<REDACTED_CREDS>@\2")
]

def redact_content(content: str) -> str:
    """
    Applies regular expression rules to sanitize sensitive information from captured log strings.
    """
    if not content:
        return content
        
    sanitized = content
    for pattern, replacement in _REDACTION_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized)
    return sanitized
