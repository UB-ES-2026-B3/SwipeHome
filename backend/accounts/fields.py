def normalize_account_email(email):
    """Canonical account identity, including the entire address and whitespace."""
    return email.strip().lower() if isinstance(email, str) else email
