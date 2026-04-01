# config.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Config:
    # Flask / DB
    # IMPORTANT: set SECRET_KEY in environment for production.
    SECRET_KEY = os.environ.get("SECRET_KEY") or "CHANGE_ME"
    if SECRET_KEY == "CHANGE_ME" and os.environ.get("FLASK_ENV") != "development":
        import warnings
        warnings.warn(
            "SECRET_KEY is not set! Set the SECRET_KEY environment variable for production.",
            stacklevel=1,
        )
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(BASE_DIR / "factory.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Device settings (env overrides supported)
    DEVICE_IP = os.environ.get("DEVICE_IP", "10.0.0.5")
    USERNAME = os.environ.get("DEVICE_USERNAME", "")
    PASSWORD = os.environ.get("DEVICE_PASSWORD", "")
    DEVICE_TZ_OFFSET = os.environ.get("DEVICE_TZ_OFFSET", "+02:00")
    DEVICE_SCHEME = os.environ.get("DEVICE_SCHEME", "http")  # or "https"
    DEVICE_PORT = int(os.environ.get("DEVICE_PORT", "0")) or None
    DEVICE_CONNECT_TIMEOUT = float(os.environ.get("DEVICE_CONNECT_TIMEOUT", "5"))
    DEVICE_READ_TIMEOUT = float(os.environ.get("DEVICE_READ_TIMEOUT", "30"))
    SYNC_LOOKBACK_DAYS = int(os.environ.get("SYNC_LOOKBACK_DAYS", "30"))
    DEVICE_HTTP_AUTH = os.environ.get("DEVICE_HTTP_AUTH", "auto")  # auto | digest | basic
    # Earliest date for Sync All; if set, starts from here instead of 2000-01-01 (format YYYY-MM-DD)
    SYNC_ALL_START = os.environ.get("SYNC_ALL_START", None)

    LEAVE_FORM_TEMPLATE = os.environ.get(
        "LEAVE_FORM_TEMPLATE",
        str(BASE_DIR / "static" / "files" / "62 - Application for leave.pdf"),
    )

    # Attendance/payroll policy
    NORMAL_WEEKLY_HOURS = float(os.environ.get("NORMAL_WEEKLY_HOURS", "40"))
    # When two consecutive check-ins are seen within a day and the gap is >= N minutes,
    # infer the later one as a check-out for pairing/flags during recomputation (non-destructive).
    CONSECUTIVE_IN_TO_OUT_MIN_MINUTES = int(os.environ.get("CONSECUTIVE_IN_TO_OUT_MIN_MINUTES", "240"))
    # Disable manual night shift planning (NightWeekPlan) and rely entirely on event-based detection
    USE_NIGHT_PLAN = (os.environ.get("USE_NIGHT_PLAN", "0").strip().lower() in ("1","true","yes"))

    # Feature flags to control module visibility/registration for staged rollout/testing
    # Default ON for day-to-day use; disable explicitly in production-only deployments.
    FEATURE_ATTENDANCE = (os.environ.get("FEATURE_ATTENDANCE", "1").strip().lower() in ("1","true","yes"))
    FEATURE_ANALYTICS  = (os.environ.get("FEATURE_ANALYTICS", "1").strip().lower() in ("1","true","yes"))
