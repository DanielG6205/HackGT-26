class ServiceError(RuntimeError):
    """A recoverable service failure with a safe, user-facing message."""


def service_error(service, exc):
    # Do not print raw SDK exceptions: they may contain request headers or URLs.
    status = getattr(exc, "status_code", None)
    code = getattr(exc, "code", None)
    grpc_status = getattr(code(), "name", "") if callable(code) else ""
    # Inspect only to classify; never return raw service payloads.
    details = getattr(exc, "details", None)
    detail_text = details() if callable(details) else ""
    invalid_key = "incorrect api key" in str(detail_text).lower()
    if invalid_key:
        detail = "incorrect API key; replace XAI_API_KEY in .env with a valid xAI key" if service == "xAI/Grok" else "incorrect API key"
    elif status in (401, 403) or grpc_status in {"UNAUTHENTICATED", "PERMISSION_DENIED"}:
        detail = "authentication/access denied; check API key and permissions"
    elif status == 400 or grpc_status == "INVALID_ARGUMENT":
        detail = "request rejected; check API key format, model name, and request settings"
    elif status == 429 or grpc_status == "RESOURCE_EXHAUSTED":
        detail = "quota/rate limit reached; check credits or retry later"
    else:
        detail = "check network, account credits, model/voice access, and audio device permissions"
    return ServiceError(f"{service}: {type(exc).__name__}; {detail}")
