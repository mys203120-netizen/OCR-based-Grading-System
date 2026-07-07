from app.core.config import Settings
from app.main import create_app


def test_create_app_keeps_services_on_app_state() -> None:
    settings = Settings(
        ai_provider="mock",
        queue_provider="inline",
        message_provider="mock",
        database_url="sqlite+aiosqlite:///:memory:",
    )

    app = create_app(settings)

    assert app.state.settings is settings
    assert {route.path for route in app.routes} >= {"/health", "/storage"}
