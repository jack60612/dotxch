from enum import Enum


class ResolutionStatusCode(Enum):
    NOT_FOUND = 0
    INVALID = 1
    CONFLICTING = 2
    EXPIRED = 3
    GRACE_PERIOD = 4
    FOUND = 5  # when first found
    LATEST = 6  # after pulling latest state from blockchain
