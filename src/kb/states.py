"""Document life cycle. Only the service changes a status, and only along these transitions."""
from typing import Optional

from src.kb.errors import InvalidTransition

UPLOADED, VALIDATED, STAGED, APPROVED, PUBLISHED = "uploaded", "validated", "staged", "approved", "published"
REJECTED, WITHDRAWN, SUPERSEDED, SUSPENDED = "rejected", "withdrawn", "superseded", "suspended"
STATES = (UPLOADED, VALIDATED, STAGED, APPROVED, PUBLISHED, REJECTED, WITHDRAWN, SUPERSEDED, SUSPENDED)

TRANSITIONS = {
    None: {UPLOADED},
    UPLOADED: {VALIDATED, REJECTED},
    VALIDATED: {STAGED, REJECTED, UPLOADED},          # back to uploaded: metadata corrected, revalidation required
    STAGED: {APPROVED, REJECTED},
    APPROVED: {PUBLISHED, REJECTED},
    PUBLISHED: {WITHDRAWN, SUPERSEDED, SUSPENDED},    # suspended: taken out of the public index by a rollback
    SUSPENDED: {PUBLISHED, WITHDRAWN},                # back to published only with a recorded decision
    REJECTED: set(),
    WITHDRAWN: set(),
    SUPERSEDED: set(),
}
# Making a withdrawn or superseded document public again is never an ordinary transition: it is only possible
# through a rollback (or reconciliation) that carries an explicit, recorded reinstatement approval.
REINSTATEMENT = {WITHDRAWN: {PUBLISHED}, SUPERSEDED: {PUBLISHED}}

# Which documents each kind of store version contains
VISIBLE = {"public": frozenset({PUBLISHED}), "staging": frozenset({PUBLISHED, STAGED, APPROVED})}


def check_transition(current: Optional[str], new: str, reinstatement: bool = False) -> None:
    if new not in STATES:
        raise InvalidTransition(f"unknown status {new!r}")
    allowed = TRANSITIONS.get(current, set()) | (REINSTATEMENT.get(current, set()) if reinstatement else set())
    if new not in allowed:
        raise InvalidTransition(f"cannot change status from {current!r} to {new!r}")


def visible_in(kind: str, status: str) -> bool:
    return status in VISIBLE[kind]
