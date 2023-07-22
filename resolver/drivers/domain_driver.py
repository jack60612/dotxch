from dataclasses import dataclass
from typing import Any

from blspy import G2Element
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle

from resolver.drivers.puzzle_class import BasePuzzle, PuzzleType
from resolver.puzzles.puzzles import DOMAIN_PH_MOD, DOMAIN_PH_MOD_HASH


@dataclass(kw_only=True)
class DomainPuzzle(BasePuzzle):
    puzzle_type: PuzzleType = PuzzleType.DOMAIN
    raw_puzzle: Program = DOMAIN_PH_MOD
    puzzle_mod: bytes32 = DOMAIN_PH_MOD_HASH
    num_curry_args: int = 1
    num_solution_args: int = 0

    def __post_init__(self) -> None:
        if self.domain_name is not None:
            self.curry_args = [Program.to(self.domain_name)]
        else:
            raise ValueError("Domain Name is required for Domain Puzzle")

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend, _: Any = None) -> "DomainPuzzle":
        spend_super_class = super().from_coin_spend(coin_spend, PuzzleType.DOMAIN)
        if spend_super_class.puzzle_mod != DOMAIN_PH_MOD_HASH:
            raise ValueError("Incorrect Puzzle Driver")
        assert spend_super_class.domain_name is not None
        return cls(domain_name=spend_super_class.domain_name)

    def to_coin_spend(self, coin: Coin) -> CoinSpend:
        assert coin.amount == 1
        return super().to_coin_spend(coin)

    async def to_spend_bundle(self, coin: Coin, _: Any = None) -> SpendBundle:
        coin_spends = [self.to_coin_spend(coin)]
        return SpendBundle(coin_spends, G2Element())
