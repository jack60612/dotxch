from typing import Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD,
    SINGLETON_MOD_HASH,
)

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


class DomainInnerPuzzle(BasePuzzle):
    ...


class RegistrationFeePuzzle(BasePuzzle):
    def __init__(self, domain_puzzle: DomainPuzzle, domain_inner: DomainInnerPuzzle, parent_id: bytes32):
        self.domain_puzzle = domain_puzzle
        self.domain_inner = domain_inner
        self.domain_name = domain_puzzle.domain_name
        self.parent_id = parent_id
        solutions_list = [self.domain_name, self.parent_id]
        super().__init__(PuzzleType(1), REGISTRATION_FEE_MOD, REGISTRATION_FEE_MOD_HASH, 0, 5, [], solutions_list)


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
