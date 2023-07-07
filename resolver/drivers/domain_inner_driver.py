from typing import Optional

from blspy import G1Element
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle

from resolver.drivers.puzzle_class import BasePuzzle, PuzzleType
from resolver.puzzles.puzzles import INNER_SINGLETON_MOD
from resolver.types.domain_metadata import DomainMetadataRaw, decode_metadata_keys


class DomainInnerPuzzle(BasePuzzle):
    def __init__(
        self,
        domain_name: str,
        pub_key: G1Element,
        metadata: DomainMetadataRaw,
    ):
        self.cur_pub_key: G1Element = pub_key
        self.cur_metadata: DomainMetadataRaw = metadata
        # because the puzzle needs its hash with the domain,
        # we calculate it below, and modify the puzzle, unlike other drivers.
        puzzle_mod = INNER_SINGLETON_MOD.curry(Program.to(domain_name))
        puzzle_mod_hash = puzzle_mod.get_tree_hash()
        curry_args = [puzzle_mod_hash, pub_key, metadata]
        super().__init__(PuzzleType.INNER, puzzle_mod, puzzle_mod_hash, 3, 4, curry_args, domain_name=domain_name)

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend, _=None) -> "DomainInnerPuzzle":
        spend_super_class = super().from_coin_spend(coin_spend, PuzzleType.INNER)
        assert spend_super_class.domain_name is not None
        if spend_super_class.raw_puzzle.uncurry()[0] != INNER_SINGLETON_MOD:
            raise ValueError("Incorrect Puzzle Driver")

        # load curried / original args
        _, existing_pub_key, existing_metadata = spend_super_class.curry_args
        # check solution for changed args, and if they were changed, use them instead.
        _, _, sol_metadata, sol_pub_key = spend_super_class.solution_args
        pub_key = sol_pub_key if sol_pub_key else existing_pub_key
        clvm_metadata: list[tuple[bytes, bytes]] = sol_metadata if sol_metadata else existing_metadata
        return cls(spend_super_class.domain_name, pub_key, decode_metadata_keys(clvm_metadata))

    def generate_solution_args(
        self,
        coin: Coin,
        new_pubkey: Optional[G1Element] = None,
        new_metadata: Optional[DomainMetadataRaw] = None,
        renew: bool = False,
    ) -> None:
        # Args are: Renew, new_metadata, new_pubkey
        if new_pubkey is not None:
            if new_metadata is None:
                new_metadata = self.cur_metadata
            sol_args = [0, new_metadata, new_pubkey]
        elif renew:
            sol_args = [1, new_metadata if new_metadata else False, 0]
        elif new_metadata is not None:
            sol_args = [0, new_metadata, 0]
        else:
            raise ValueError("No arguments provided")
        # sometimes we make a custom spend, so we need to add the coin parent id now.
        self.solution_args = [coin.parent_coin_info] + sol_args  # Override solution args

    def to_coin_spend(self, coin: Coin) -> CoinSpend:
        if self.solution_args[0] != coin.parent_coin_info:
            self.solution_args = [coin.parent_coin_info] + self.solution_args  # add coin parent id first
        if not self.is_spendable_puzzle:
            raise ValueError("Other arguments have not been generated")
        return super().to_coin_spend(coin)

    async def to_spend_bundle(self, coin: Coin, _) -> SpendBundle:
        raise NotImplementedError("Inner puzzles are not designed to be spent unwrapped.")
