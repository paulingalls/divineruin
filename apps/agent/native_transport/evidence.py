def reject_credentials(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if any(word in str(key).lower() for word in ("token", "secret", "credential")):
                raise ValueError("native transport evidence contains a credential field")
            reject_credentials(child)
    elif isinstance(value, list):
        for child in value:
            reject_credentials(child)
