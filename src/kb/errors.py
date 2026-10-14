"""Errors raised by the knowledge-base engine (all subclasses of KBError)."""


class KBError(Exception):
    """Base class for knowledge-base errors."""


class InvalidIdentifier(KBError):
    pass


class InvalidTransition(KBError):
    pass


class DuplicateDocument(KBError):
    pass


class UnknownDocument(KBError):
    pass


class PermissionDenied(KBError):
    pass


class LockedError(KBError):
    pass


class ValidationFailed(KBError):
    pass


class IntegrityError(KBError):
    """A store version, pointer, registry or cached file does not match its recorded hashes."""


class OverrideActive(KBError):
    """An emergency rollback is in force; publishing changes are blocked until reconciliation."""


class ReinstatementRequired(KBError):
    """A rollback would make a withdrawn or superseded document public again without a recorded approval."""
