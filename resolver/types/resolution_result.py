from dataclasses import dataclass
from typing import Optional

from resolver.drivers.domain_record import DomainRecord
from resolver.types.resolution_status_code import ResolutionStatusCode


@dataclass(frozen=True)
class ResolutionResult:
    """
    This class is used to allow the resolver to return a domain record or a status code.
    """

    domain_name: str
    status_code: ResolutionStatusCode
    domain_record: Optional[DomainRecord]
