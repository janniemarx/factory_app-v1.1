from __future__ import annotations

import os


class Config:
    """Minimal config for the rewrite.

    This defaults to reading env vars so it can run side-by-side with the legacy app.
    """

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev")

    # Reuse legacy DATABASE_URL / SQLALCHEMY_DATABASE_URI if set
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "SQLALCHEMY_DATABASE_URI",
        os.environ.get("DATABASE_URL", "sqlite:///factory_app_v3.sqlite"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Feature flags (attendance intentionally not present)
    FEATURE_ANALYTICS = bool(int(os.environ.get("FEATURE_ANALYTICS", "0")))

    # If you need local time conversions
    DEVICE_TZ_OFFSET = os.environ.get("DEVICE_TZ_OFFSET", "+02:00")
