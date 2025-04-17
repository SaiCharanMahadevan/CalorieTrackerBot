from typing import Optional

def sanitize_token(token: Optional[str]) -> Optional[str]:
    """Sanitize the token by removing whitespace and non-printable characters."""
    if token:
        # Keep only printable ASCII characters for typical tokens
        # (Ensure this logic matches token requirements)
        return ''.join(c for c in token if 32 <= ord(c) <= 126) 
    return None

# Add other utility functions here in the future if needed 