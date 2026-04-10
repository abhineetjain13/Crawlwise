from __future__ import annotations


class CrawlerError(RuntimeError):
    """Base class for crawler service errors."""


class CrawlerConfigurationError(CrawlerError, ValueError):
    """Raised when crawler configuration is invalid."""


class AcquisitionError(CrawlerError):
    """Base class for acquisition-stage failures."""


class AcquisitionFailureError(AcquisitionError):
    """Raised when acquisition cannot produce usable content."""


class AcquisitionTimeoutError(AcquisitionError, TimeoutError):
    """Raised when acquisition exceeds configured timeout."""


class ProxyPoolExhaustedError(AcquisitionError):
    """Raised when no usable proxies remain for acquisition."""


class BrowserError(AcquisitionError):
    """Raised for browser-rendering failures during acquisition."""


class BrowserNavigationError(BrowserError):
    """Raised when browser navigation lands on an unrecoverable browser error."""


class ExtractionError(CrawlerError):
    """Base class for extraction-stage failures."""


class ExtractionParseError(ExtractionError):
    """Raised when extraction cannot parse acquired content."""


class PipelineError(CrawlerError):
    """Base class for pipeline-stage failures."""


class PipelineWriteError(PipelineError):
    """Raised when pipeline persistence fails."""


class AdapterError(CrawlerError):
    """Base class for adapter-specific failures."""


class RunControlError(CrawlerError):
    """Base class for control-plane run interruptions (pause/kill)."""
