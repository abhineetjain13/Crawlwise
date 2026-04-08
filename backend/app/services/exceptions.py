from __future__ import annotations


class CrawlerError(RuntimeError):
    """Base class for crawler service errors."""


class CrawlerConfigurationError(CrawlerError, ValueError):
    """Raised when crawler configuration is invalid."""


class AcquisitionError(CrawlerError):
    """Base class for acquisition-stage failures."""


class AcquisitionTimeoutError(AcquisitionError, TimeoutError):
    """Raised when acquisition exceeds configured timeout."""


class ProxyPoolExhaustedError(AcquisitionError):
    """Raised when no usable proxies remain for acquisition."""


class BrowserError(AcquisitionError):
    """Raised for browser-rendering failures during acquisition."""


class ExtractionError(CrawlerError):
    """Base class for extraction-stage failures."""


class AdapterError(CrawlerError):
    """Base class for adapter-specific failures."""


class RunControlError(CrawlerError):
    """Base class for control-plane run interruptions (pause/kill)."""
