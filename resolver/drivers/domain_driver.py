from blspy import G2Element
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle

from resolver.drivers.puzzle_class import BasePuzzle, PuzzleType
from resolver.puzzles.puzzles import DOMAIN_PH_MOD, DOMAIN_PH_MOD_HASH


class DomainPuzzle(BasePuzzle):
    def __init__(self, domain_name: str):
        super().__init__(
            PuzzleType.DOMAIN, DOMAIN_PH_MOD, DOMAIN_PH_MOD_HASH, 1, 0, [domain_name], domain_name=domain_name
        )

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend, _=None) -> "DomainPuzzle":
        spend_super_class = super().from_coin_spend(coin_spend, PuzzleType.DOMAIN)
        if spend_super_class.puzzle_mod != DOMAIN_PH_MOD_HASH:
            raise ValueError("Incorrect Puzzle Driver")
        assert spend_super_class.domain_name is not None
        return cls(spend_super_class.domain_name)

    def to_coin_spend(self, coin: Coin) -> CoinSpend:
        assert coin.amount == 1
        return super().to_coin_spend(coin)

    async def to_spend_bundle(self, coin: Coin, _) -> SpendBundle:
        coin_spends = [self.to_coin_spend(coin)]
        return SpendBundle(coin_spends, G2Element())
