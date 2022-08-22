from typing import Any, List, Optional, Tuple, Union

from blspy import G1Element, G2Element, PrivateKey
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD,
    SINGLETON_MOD_HASH,
)
from chia.wallet.sign_coin_spends import sign_coin_spends

from resolver.drivers.puzzle_class import BasePuzzle, PuzzleType
from resolver.puzzles.puzzles import (
    DOMAIN_PH_MOD,
    DOMAIN_PH_MOD_HASH,
    INNER_SINGLETON_MOD,
    REGISTRATION_FEE_MOD,
    REGISTRATION_FEE_MOD_HASH,
)


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
        return cls(spend_super_class.domain_name)

    def to_coin_spend(self, coin: Coin) -> CoinSpend:
        assert coin.amount == 1
        return super().to_coin_spend(coin)

    async def to_spend_bundle(self, coin: Coin, _) -> SpendBundle:
        coin_spends = [self.to_coin_spend(coin)]
        return SpendBundle(coin_spends, G2Element())


class RegistrationFeePuzzle(BasePuzzle):
    def __init__(
        self,
        domain_name: str,
        domain_outer_ph: bytes32,
        fee_parent_id: bytes32,
        singleton_launcher_id: bytes32,
        singleton_parent_id: bytes32,
    ):
        self.domain_outer_ph = domain_outer_ph
        solutions_list = [
            domain_name,
            self.domain_outer_ph,
            fee_parent_id,
            singleton_launcher_id,
            singleton_parent_id,
        ]
        super().__init__(
            PuzzleType.FEE,
            REGISTRATION_FEE_MOD,
            REGISTRATION_FEE_MOD_HASH,
            0,
            5,
            [],
            solutions_list,
            domain_name=domain_name,
        )

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend, _=None) -> "RegistrationFeePuzzle":
        spend_super_class = super().from_coin_spend(coin_spend, PuzzleType.FEE)
        if spend_super_class.puzzle_mod != REGISTRATION_FEE_MOD_HASH:
            raise ValueError("Incorrect Puzzle Driver")
        _, outer_ph, fee_parent_id, singleton_launcher_id, singleton_parent_id = spend_super_class.solution_args
        return cls(spend_super_class.domain_name, outer_ph, fee_parent_id, singleton_launcher_id, singleton_parent_id)

    async def to_spend_bundle(self, coin: Coin, _=None) -> SpendBundle:
        coin_spends = [self.to_coin_spend(coin)]
        return SpendBundle(coin_spends, G2Element())


class DomainInnerPuzzle(BasePuzzle):
    def __init__(
        self,
        domain_name: str,
        pub_key: G1Element,
        metadata: List[Tuple[Any]],
    ):
        self.cur_pub_key = pub_key
        self.cur_metadata = metadata
        # because the puzzle needs its hash with the domain,
        # we calculate it below, and modify the puzzle, unlike other drivers.
        puzzle_mod = INNER_SINGLETON_MOD.curry(Program.to(domain_name))
        puzzle_mod_hash = puzzle_mod.get_tree_hash()
        curry_args = [puzzle_mod_hash, pub_key, metadata]
        super().__init__(PuzzleType.INNER, puzzle_mod, puzzle_mod_hash, 3, 4, curry_args, domain_name=domain_name)

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend, _=None) -> "DomainInnerPuzzle":
        spend_super_class = super().from_coin_spend(coin_spend, PuzzleType.INNER)
        if spend_super_class.raw_puzzle.uncurry()[0] != INNER_SINGLETON_MOD:
            raise ValueError("Incorrect Puzzle Driver")
        curry_args = spend_super_class.curry_args
        return cls(spend_super_class.domain_name, curry_args[1], curry_args[2])

    def generate_solution_args(
        self,
        new_pubkey: Optional[Union[G1Element, bool]] = None,
        new_metadata: Optional[Union[List[Tuple[Any]], bool]] = None,
        renew: bool = False,
    ) -> None:
        # Args are: Renew, new_metadata, new_pubkey
        if new_pubkey is not None:
            if new_metadata is None:
                new_metadata = self.cur_metadata
            sol_args = [0, new_metadata, new_pubkey]
        elif renew:
            if new_metadata is None:
                new_metadata = False
            sol_args = [1, new_metadata, 0]
        elif new_metadata is not None:
            sol_args = [0, new_metadata, 0]
        else:
            raise ValueError("No arguments provided")
        self.solution_args += sol_args

    def to_coin_spend(self, coin: Coin) -> CoinSpend:
        if self.solution_args[0] != coin.parent_coin_info:
            self.solution_args = [coin.parent_coin_info] + self.solution_args  # add coin parent id first
        if not self.is_spendable_puzzle:
            raise ValueError("Other arguments have not been generated")
        return super().to_coin_spend(coin)

    async def to_spend_bundle(self, coin: Coin, _) -> SpendBundle:
        raise NotImplementedError("Inner puzzles are not designed to be spent unwrapped.")


class DomainOuterPuzzle(BasePuzzle):
    def __init__(
        self,
        sig_additional_data: bytes,
        max_block_cost: int,
        launcher_id: bytes32,
        lineage_proof: LineageProof,
        inner_puzzle: DomainInnerPuzzle,
    ):
        self.domain_puzzle = inner_puzzle
        self.lineage_proof = lineage_proof
        # This is: (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH)) & the inner puzzle
        curry_args = [(SINGLETON_MOD_HASH, (launcher_id, SINGLETON_LAUNCHER_HASH)), inner_puzzle.complete_puzzle()]
        # coin_amount will be replaced with the actual coin amount below.
        solution_args = [self.lineage_proof.to_program(), "coin_amount", inner_puzzle.generate_solution()]
        # network constants
        self.AGG_SIG_ME_ADDITIONAL_DATA = sig_additional_data
        self.MAX_BLOCK_COST_CLVM = max_block_cost
        super().__init__(
            PuzzleType.OUTER,
            SINGLETON_MOD,
            SINGLETON_MOD_HASH,
            2,
            3,
            curry_args,
            solution_args,
            inner_puzzle.domain_name,
        )
        # TODO: Implement from_coin_spend & creation function.

    def to_coin_spend(self, coin: Coin) -> CoinSpend:
        self.solution_args[1] = coin.amount  # replace the placeholder amount with the actual amount
        return super().to_coin_spend(coin)

    async def to_spend_bundle(self, private_key: PrivateKey, coin: Coin) -> SpendBundle:
        if private_key.get_g1() != self.domain_puzzle.cur_pub_key:
            raise ValueError("Private key does not match public key")
        coin_spend = self.to_coin_spend(coin)

        async def priv_key(pk: G1Element) -> PrivateKey:
            return private_key

        return await sign_coin_spends(
            [coin_spend],
            priv_key,
            self.AGG_SIG_ME_ADDITIONAL_DATA,
            self.MAX_BLOCK_COST_CLVM,
        )
