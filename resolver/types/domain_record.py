from dataclasses import dataclass

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint32, uint64

from resolver.drivers.domain_outer_driver import DomainOuterPuzzle
from resolver.puzzles.domain_constants import GRACE_PERIOD
from resolver.types.domain_metadata import DomainMetadata
from resolver.types.resolution_status_code import ResolutionStatusCode


@dataclass(frozen=True)
class DomainRecord:
    """
    This class is used to represent the data for a domain in the blockchain.
    """

    creation_height: uint32  # this is also the spend height of the 1st coin.
    creation_timestamp: uint64  # this is used to easily determine how old a domain is.
    registration_update_height: uint32  # The block where the registration was last updated
    state_update_height: uint32  # The block where the state was last updated
    expiration_timestamp: uint64  # The domain expiry time.
    domain_class: DomainOuterPuzzle  # class matching the spend below.
    domain_metadata: DomainMetadata  # metadata for the domain
    full_spend: CoinSpend  # last checked spend of the domain singleton coin.

    @classmethod
    def from_coin_spend(
        cls,
        creation_height: uint32,
        creation_timestamp: uint64,
        registration_update_height: uint32,
        state_update_height: uint32,
        expiration_timestamp: uint64,
        spend: CoinSpend,
        const_tuple: tuple[bytes, int],
    ) -> "DomainRecord":
        # const_tuple is a tuple of (sig_additional_data, max_block_cost)
        d_class = DomainOuterPuzzle.from_outer_coin_spend(spend, const_tuple)
        metadata = DomainMetadata.from_raw(d_class.domain_puzzle.cur_metadata)
        return cls(
            creation_height,
            creation_timestamp,
            registration_update_height,
            state_update_height,
            expiration_timestamp,
            d_class,
            metadata,
            spend,
        )

    @property
    def spend_height(self) -> uint32:
        return self.state_update_height

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
