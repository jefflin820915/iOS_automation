"""Shared exceptions for iGHA page objects."""
class OOBEInternalErrorException(Exception):
    """Raised when GHA displays 'Internal error encountered.' modal during post-commissioning OOBE."""