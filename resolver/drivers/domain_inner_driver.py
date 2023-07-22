from dataclasses import dataclass, field
from typing import Any, Optional

from blspy import G1Element
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle

from resolver.drivers.puzzle_class import BasePuzzle, PuzzleType
from resolver.puzzles.puzzles import INNER_SINGLETON_MOD
from resolver.types.domain_metadata import DomainMetadataRaw, decode_metadata_keys


@dataclass(kw_only=True)
class DomainInnerPuzzle(BasePuzzle):
    cur_pub_key: G1Element
    cur_metadata: DomainMetadataRaw
    raw_puzzle: Program = field(init=False)  # we do this in the post init
    puzzle_mod: bytes32 = field(init=False)  # we do this in the post init
    puzzle_type: PuzzleType = PuzzleType.INNER
    num_curry_args: int = 3
    num_solution_args: int = 4

    def __post_init__(self) -> None:
        if self.domain_name is None:
            raise ValueError("Domain Name is required for Domain Inner Puzzle")
        # because the puzzle needs its hash with the domain,
        # we calculate it below, and modify the puzzle, unlike other drivers.
        puzzle_mod = INNER_SINGLETON_MOD.curry(Program.to(self.domain_name))
        puzzle_mod_hash = puzzle_mod.get_tree_hash()
        curry_args = [puzzle_mod_hash, self.cur_pub_key, self.cur_metadata]
        super().__init__(
            puzzle_type=self.puzzle_type,
            raw_puzzle=puzzle_mod,
            puzzle_mod=puzzle_mod_hash,
            num_curry_args=3,
            num_solution_args=4,
            curry_args=curry_args,
            domain_name=self.domain_name,
        )

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend, _: Any = None) -> "DomainInnerPuzzle":
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
        return cls(
            domain_name=spend_super_class.domain_name,
            cur_pub_key=pub_key,
            cur_metadata=decode_metadata_keys(clvm_metadata),
        )

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

    async def to_spend_bundle(self, coin: Coin, _: Any = None) -> SpendBundle:
        raise NotImplementedError("Inner puzzles are not designed to be spent unwrapped.")
