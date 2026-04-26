from fastapi import APIRouter, HTTPException, Request

from sanad_api.config import get_settings
from sanad_api.database import SessionLocal
from sanad_api.services.providers import ProviderConfigurationError, SmartTmtProvider, get_provider
from sanad_api.services.demo_reset import reset_demo_state

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    try:
        provider = get_provider(settings.active_provider)
        provider_status = {"name": provider.name, "implemented": provider.is_implemented}
        # Enrich with smart provider status if applicable
        if isinstance(provider, SmartTmtProvider):
            smart_status = provider.get_status()
            provider_status["tier"] = smart_status["last_provider_used"]
            provider_status["official_api_configured"] = smart_status["official_configured"]
            provider_status["fallback_enabled"] = smart_status["fallback_enabled"]
            provider_status["api_available"] = smart_status["api_available"]
    except ProviderConfigurationError as exc:
        provider_status = {"name": settings.active_provider, "implemented": False, "error": str(exc)}
    return {
        "status": "ok",
        "database": "configured",
        "storage_root": str(settings.storage_root),
        "provider": provider_status,
    }


@router.get("/debug/provider")
def debug_provider() -> dict:
    settings = get_settings()
    try:
        provider = get_provider(settings.active_provider)
    except ProviderConfigurationError as exc:
        return {
            "active_provider": settings.active_provider,
            "implemented": False,
            "notes": str(exc),
            "todos": [],
            "configured_endpoint": False,
            "configured_api_key": False,
            "auth_method": None,
            "timeout_seconds": None,
            "batch_size": None,
            "smart_status": None,
        }

    result = {
        "active_provider": provider.name,
        "implemented": provider.is_implemented,
        "notes": provider.notes,
        "todos": getattr(provider, "todos", []),
        "configured_endpoint": bool(getattr(provider, "endpoint", None)),
        "configured_api_key": bool(getattr(provider, "api_key", None)),
        "auth_method": getattr(provider, "auth_method", None),
        "timeout_seconds": getattr(provider, "timeout_seconds", None),
        "batch_size": getattr(provider, "batch_size", None),
    }

    # Provider chain details
    if isinstance(provider, SmartTmtProvider):
        smart_status = provider.get_status()
        result["smart_status"] = smart_status
        result["official_endpoint"] = settings.tmt_official_endpoint
        result["legacy_endpoint"] = settings.tmt_api_endpoint
        result["configured_api_key"] = bool(settings.tmt_api_key)
    else:
        result["smart_status"] = None

    return result


@router.post("/debug/reset-demo")
def debug_reset_demo(request: Request) -> dict:
    settings = get_settings()
    if not settings.enable_demo_reset:
        raise HTTPException(status_code=404, detail="Demo reset is disabled.")

    session_local = getattr(request.app.state, "session_local", SessionLocal)
    return reset_demo_state(session_local=session_local, storage_root=settings.storage_root)
