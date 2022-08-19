from typing import Optional, List, Tuple, Any

from blspy import G1Element, PrivateKey, G2Element
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
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
    INNER_SINGLETON_MOD_HASH,
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
    def __init__(self, sig_additional_data: bytes, max_block_cost: int, domain_name: str, pub_key: G1Element, metadata: List[Tuple[Any]]):
        self.domain_name = domain_name
        self.cur_pub_key = pub_key
        self.cur_metadata = metadata
        self.AGG_SIG_ME_ADDITIONAL_DATA = sig_additional_data
        self.MAX_BLOCK_COST_CLVM = max_block_cost
        new_mod_hash = INNER_SINGLETON_MOD.curry(domain_name).get_tree_hash()
        curry_args = [domain_name, new_mod_hash, pub_key, metadata]
        super().__init__(PuzzleType(2), INNER_SINGLETON_MOD, INNER_SINGLETON_MOD_HASH, 4, 4, curry_args)

    async def to_spend_bundle(
        self,
        private_key: PrivateKey,
        coin: Coin,
        new_pubkey: Optional[G1Element] = None,
        new_metadata: Optional[List[Tuple[Any]]] = None,
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
                new_metadata = 0
            sol_args = [1, new_metadata, 0]
        else:
            sol_args = [0, new_metadata, 0]
        self.solution_args += sol_args
        coin_spend = super().to_coin_spend(coin)
        return await sign_coin_spends(
            [coin_spend],
            private_key,
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


### Old Code
COIN_AMOUNT = 1


def singleton_puzzle(launcher_id: Program, launcher_puzzle_hash: bytes32, inner_puzzle: Program) -> Program:
    return SINGLETON_MOD.curry((SINGLETON_MOD_HASH, (launcher_id, launcher_puzzle_hash)), inner_puzzle)


# def create_beacon_puzzle(data, pub_key, version=1, mod=BEACON_MOD) -> Program:
#    return mod.curry(mod.get_tree_hash(), data, version, pub_key)


def get_inner_puzzle_reveal(coin_spend: CoinSpend) -> Program:
    if coin_spend.coin.puzzle_hash != SINGLETON_LAUNCHER_HASH:
        full_puzzle = Program.from_bytes(bytes(coin_spend.puzzle_reveal))
        r = full_puzzle.uncurry()
        if r is not None:
            _, args = r
            _, inner_puzzle = list(args.as_iter())
            return inner_puzzle


def solution_for_beacon(version, commit=None, new_pub_key=None, adapt=False) -> Program:
    if not commit:
        commit = []
    if not adapt:
        return Program.to([version, commit, new_pub_key or []])
    return Program.to([[], version, commit, new_pub_key or []])
