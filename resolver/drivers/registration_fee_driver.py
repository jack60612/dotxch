from dataclasses import InitVar, dataclass
from typing import Any

from blspy import G2Element
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle

from resolver.drivers.puzzle_class import BasePuzzle, PuzzleType
from resolver.puzzles.puzzles import REGISTRATION_FEE_MOD, REGISTRATION_FEE_MOD_HASH


@dataclass(kw_only=True)
class RegistrationFeePuzzle(BasePuzzle):
    domain_outer_ph: bytes32
    singleton_launcher_id: InitVar[bytes32]
    singleton_parent_id: InitVar[bytes32]
    puzzle_type: PuzzleType = PuzzleType.FEE
    raw_puzzle: Program = REGISTRATION_FEE_MOD
    puzzle_mod: bytes32 = REGISTRATION_FEE_MOD_HASH
    num_curry_args: int = 0
    num_solution_args: int = 4

    def __post_init__(self, singleton_launcher_id: bytes32, singleton_parent_id: bytes32) -> None:
        solutions_list = [
            self.domain_name,
            self.domain_outer_ph,
            singleton_launcher_id,
            singleton_parent_id,
        ]
        super().__init__(
            puzzle_type=self.puzzle_type,
            raw_puzzle=self.raw_puzzle,
            puzzle_mod=self.puzzle_mod,
            num_curry_args=self.num_curry_args,
            num_solution_args=self.num_solution_args,
            solution_args=solutions_list,
            domain_name=self.domain_name,
        )

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend, _: Any = None) -> "RegistrationFeePuzzle":
        spend_super_class = super().from_coin_spend(coin_spend, PuzzleType.FEE)
        if spend_super_class.puzzle_mod != REGISTRATION_FEE_MOD_HASH:
            raise ValueError("Incorrect Puzzle Driver")
        _, outer_ph, singleton_launcher_id, singleton_parent_id = spend_super_class.solution_args
        assert spend_super_class.domain_name is not None
        return cls(
            domain_name=spend_super_class.domain_name,
            domain_outer_ph=outer_ph,
            singleton_launcher_id=singleton_launcher_id,
            singleton_parent_id=singleton_parent_id,
        )

    async def to_spend_bundle(self, coin: Coin, _: Any = None) -> SpendBundle:
        coin_spends = [self.to_coin_spend(coin)]
        return SpendBundle(coin_spends, G2Element())
