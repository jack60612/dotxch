from blspy import G2Element
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle

from resolver.drivers.puzzle_class import BasePuzzle, PuzzleType
from resolver.puzzles.puzzles import REGISTRATION_FEE_MOD, REGISTRATION_FEE_MOD_HASH


class RegistrationFeePuzzle(BasePuzzle):
    def __init__(
        self,
        domain_name: str,
        domain_outer_ph: bytes32,
        singleton_launcher_id: bytes32,
        singleton_parent_id: bytes32,
    ):
        self.domain_outer_ph = domain_outer_ph
        solutions_list = [
            domain_name,
            self.domain_outer_ph,
            singleton_launcher_id,
            singleton_parent_id,
        ]
        super().__init__(
            PuzzleType.FEE,
            REGISTRATION_FEE_MOD,
            REGISTRATION_FEE_MOD_HASH,
            0,
            4,
            [],
            solutions_list,
            domain_name=domain_name,
        )

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend, _=None) -> "RegistrationFeePuzzle":
        spend_super_class = super().from_coin_spend(coin_spend, PuzzleType.FEE)
        if spend_super_class.puzzle_mod != REGISTRATION_FEE_MOD_HASH:
            raise ValueError("Incorrect Puzzle Driver")
        _, outer_ph, fee_parent_id, singleton_launcher_id = spend_super_class.solution_args
        assert spend_super_class.domain_name is not None
        return cls(spend_super_class.domain_name, outer_ph, fee_parent_id, singleton_launcher_id)

    async def to_spend_bundle(self, coin: Coin, _=None) -> SpendBundle:
        coin_spends = [self.to_coin_spend(coin)]
        return SpendBundle(coin_spends, G2Element())
