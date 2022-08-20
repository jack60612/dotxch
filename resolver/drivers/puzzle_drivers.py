from typing import Any, List, Optional, Tuple, Union

from blspy import G1Element, G2Element, PrivateKey
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle

"""
these will be uncommented later
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD,
    SINGLETON_MOD_HASH,
)
"""
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
        self.domain_name = domain_name
        super().__init__(PuzzleType(0), DOMAIN_PH_MOD, DOMAIN_PH_MOD_HASH, 1, 1, [domain_name])

    def to_coin_spend(self, coin: Coin) -> CoinSpend:
        self.solution_args.append(coin.amount)
        return super().to_coin_spend(coin)

    async def to_spend_bundle(self, coin: Coin) -> SpendBundle:
        coin_spends = [self.to_coin_spend(coin)]
        return SpendBundle(coin_spends, G2Element())


class DomainInnerPuzzle(BasePuzzle):
    def __init__(
        self,
        sig_additional_data: bytes,
        max_block_cost: int,
        domain_name: str,
        pub_key: G1Element,
        metadata: List[Tuple[Any]],
    ):
        self.domain_name = domain_name
        self.cur_pub_key = pub_key
        self.cur_metadata = metadata
        self.AGG_SIG_ME_ADDITIONAL_DATA = sig_additional_data
        self.MAX_BLOCK_COST_CLVM = max_block_cost
        # because the puzzle needs its hash with the domain,
        # we calculate it below, and modify the puzzle, unlike other drivers.
        puzzle_mod = INNER_SINGLETON_MOD.curry(Program.to(domain_name))
        puzzle_mod_hash = puzzle_mod.get_tree_hash()
        curry_args = [puzzle_mod_hash, pub_key, metadata]
        super().__init__(PuzzleType(2), puzzle_mod, puzzle_mod_hash, 3, 4, curry_args)

    async def to_spend_bundle(
        self,
        private_key: PrivateKey,
        coin: Coin,
        new_pubkey: Optional[Union[G1Element, bool]] = None,
        new_metadata: Optional[Union[List[Tuple[Any]], bool]] = None,
        renew: bool = False,
    ) -> SpendBundle:
        if private_key.get_g1() != self.cur_pub_key:
            raise ValueError("Private key does not match public key")
        self.solution_args.append(coin.parent_coin_info)
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
        coin_spend = super().to_coin_spend(coin)

        async def priv_key(pk: G1Element) -> PrivateKey:
            return private_key

        return await sign_coin_spends(
            [coin_spend],
            priv_key,
            self.AGG_SIG_ME_ADDITIONAL_DATA,
            self.MAX_BLOCK_COST_CLVM,
        )


class RegistrationFeePuzzle(BasePuzzle):
    def __init__(
        self,
        domain_name: str,
        domain_inner_ph: bytes32,
        fee_parent_id: bytes32,
        singleton_launcher_id: bytes32,
        singleton_parent_id: bytes32,
    ):
        self.domain_inner_ph = domain_inner_ph
        self.domain_name = domain_name
        solutions_list = [
            self.domain_name,
            self.domain_inner_ph,
            fee_parent_id,
            singleton_launcher_id,
            singleton_parent_id,
        ]
        super().__init__(PuzzleType(1), REGISTRATION_FEE_MOD, REGISTRATION_FEE_MOD_HASH, 0, 5, [], solutions_list)

    async def to_spend_bundle(self, coin: Coin) -> SpendBundle:
        coin_spends = [self.to_coin_spend(coin)]
        return SpendBundle(coin_spends, G2Element())
