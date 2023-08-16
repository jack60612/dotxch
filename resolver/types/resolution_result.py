from dataclasses import dataclass
from typing import Any, Dict, Optional

from resolver.types.domain_record import DomainRecord
from resolver.types.resolution_status_code import ResolutionStatusCode


@dataclass(frozen=True)
class ResolutionResult:
    """
    This class is used to allow the resolver to return a domain record or a status code.
    """

    domain_name: str
    status_code: ResolutionStatusCode
    domain_record: Optional[DomainRecord]

    @classmethod
    def from_dict(cls, rr_dict: Dict[str, Any], const_tuple: tuple[bytes, int]) -> "ResolutionResult":
        return cls(
            str(rr_dict["domain_name"]),
            ResolutionStatusCode(rr_dict["status_code"]),
            DomainRecord.from_dict(rr_dict["domain_record"], const_tuple=const_tuple)
            if rr_dict["domain_record"] is not None
            else None,
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "domain_name": self.domain_name,
            "status_code": self.status_code.value,
            "domain_record": self.domain_record.to_dict() if self.domain_record is not None else None,
        }
