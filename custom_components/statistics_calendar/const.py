"""Constants for the Statistics Calendar helper."""

from homeassistant.const import Platform

DOMAIN = "statistics_calendar"
PLATFORMS = [Platform.SENSOR]

WINDOW_MODE = "window_mode"
WINDOW_ROLLING = "rolling"
WINDOW_YESTERDAY = "yesterday"

SUPPORTED_WINDOW_MODES = [WINDOW_ROLLING, WINDOW_YESTERDAY]
