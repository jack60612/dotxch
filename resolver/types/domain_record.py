from dataclasses import dataclass

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint32, uint64

from resolver.drivers.domain_outer_driver import DomainOuterPuzzle
from resolver.drivers.puzzle_class import DomainMetadata
from resolver.puzzles.domain_constants import GRACE_PERIOD, REGISTRATION_LENGTH
from resolver.types.resolution_status_code import ResolutionStatusCode


@dataclass(frozen=True)
class DomainRecord:
    """
    This class is used to represent the data for a domain in the blockchain.
    """

    domain_class: DomainOuterPuzzle
    full_spend: CoinSpend
    spend_height: uint32
    creation_height: uint32  # this is also the spend height of the 1st coin.
    creation_timestamp: uint64  # this is used to easily determine how old a domain is.
    renewal_timestamp: uint64

    @classmethod
    def from_coin_spend(
        cls,
        spend: CoinSpend,
        spend_height: uint32,
        creation_height: uint32,
        creation_timestamp: uint64,
        renewal_timestamp: uint64,
        const_tuple: tuple[bytes, int],
    ) -> "DomainRecord":
        # const_tuple is a tuple of (sig_additional_data, max_block_cost)
        d_class = DomainOuterPuzzle.from_coin_spend(spend, const_tuple)
        return cls(d_class, spend, spend_height, creation_height, creation_timestamp, renewal_timestamp)

    @property
    def domain_name(self) -> str:
        assert self.domain_class.domain_name is not None
        return self.domain_class.domain_name

    @property
    def name(self) -> bytes32:
        return self.full_spend.coin.name()

    @property
    def launcher_id(self) -> bytes32:
        return self.domain_class.launcher_id

    @property
    def cur_metadata(self) -> DomainMetadata:
        return self.domain_class.domain_puzzle.cur_metadata

    @property
    def expiration_timestamp(self) -> uint64:
        return uint64(self.renewal_timestamp + REGISTRATION_LENGTH)

    @property
    def grace_period_timestamp(self) -> uint64:
        return uint64(self.expiration_timestamp + GRACE_PERIOD)

    def is_expired(self, current_timestamp: uint64) -> bool:
        return bool(self.expiration_timestamp < current_timestamp)

    def in_grace_period(self, current_timestamp: uint64) -> bool:
        return bool(self.expiration_timestamp < current_timestamp < self.grace_period_timestamp)

    def get_status_code(self, current_timestamp: uint64) -> ResolutionStatusCode:
        if self.in_grace_period(current_timestamp):
            return ResolutionStatusCode.GRACE_PERIOD
        if self.is_expired(current_timestamp):
            return ResolutionStatusCode.EXPIRED
        else:
            return ResolutionStatusCode.FOUND