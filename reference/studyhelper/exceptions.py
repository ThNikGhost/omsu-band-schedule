"""Custom exceptions for parser module."""


class ParserException(Exception):
    """Base exception for parser errors."""


class PageLoadError(ParserException):
    """Raised when page fails to load or times out."""


class ElementNotFoundError(ParserException):
    """Raised when expected element is not found on page."""


class DataExtractionError(ParserException):
    """Raised when data extraction fails."""


class MappingError(ParserException):
    """Raised when mapping raw data to schema fails."""
