import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.snapshot.redaction import redact_content

raw_log = (
    "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c\n"
    "Some standalone JWT eyJ1c2VyIjoiYWRtaW4ifQ.eyJycmdzIjpbXX0.abcdef12345 here\n"
    "Request URL: http://localhost:8002/api?token=secret_tok_123&access_token=acc_456&refresh_token=ref_789&id_token=id_abc\n"
    "Cookie: session=sess_xyz123; tracking=track_abc\n"
    "Set-Cookie: session=sess_new; path=/\n"
    "Data: {\"password\": \"super_pass\", \"secret\": \"topsecret\", \"api_key\": \"key123\", \"apikey\": \"key456\"}\n"
    "DB URL: postgresql://postgres:password123@127.0.0.1:5432/hexa_db\n"
)

redacted = redact_content(raw_log)
print("=== REDACTED OUTPUT ===")
print(redacted)
print("=======================")
