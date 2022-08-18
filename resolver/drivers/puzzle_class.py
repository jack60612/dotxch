from enum import Enum
from typing import Any, List, Optional

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia_rs import Coin


class PuzzleType(Enum):
    DOMAIN = 0
    FEE = 1
    OUTER = 2
    INNER = 3


class BasePuzzle:
    def __init__(
        self,
        puzzle_type: PuzzleType,
        raw_puzzle: Program,
        puzzle_mod: bytes32,
        num_curry_args: int,
        num_solution_args: int,
        curry_args: Optional[List[Any]] = None,
        solution_args: Optional[List[Any]] = None,
    ):
        self.puzzle_type: PuzzleType = puzzle_type
        self.raw_puzzle: Program = raw_puzzle
        self.puzzle_mod: bytes32 = puzzle_mod
        self.num_curry_args: int = num_curry_args
        self.curry_args: List[Any] = curry_args if curry_args else []
        self.num_solution_args: int = num_solution_args
        self.solution_args: List[Any] = solution_args if solution_args else []

    @property
    def is_complete_puzzle(self) -> bool:
        return len(self.curry_args) == self.num_curry_args

    @property
    def is_spendable_puzzle(self) -> bool:
        return len(self.solution_args) == self.num_solution_args

    def complete_puzzle(self) -> Program:
        if not self.is_complete_puzzle:
            raise ValueError("Puzzle is missing curry arguments")
        if self.num_curry_args != 0:
            return self.raw_puzzle.curry(*self.curry_args)
        else:
            return self.raw_puzzle

    def complete_puzzle_hash(self) -> bytes32:
        return self.complete_puzzle().get_tree_hash()

    def generate_solution(self) -> Program:
        if not self.is_spendable_puzzle:
            raise ValueError("Puzzle is missing solution arguments.")
        if len(self.solution_args) > 1:
            return Program.to(self.solution_args)
        else:
            return Program.to(self.solution_args[0])

    def to_coin_spend(self, coin: Coin) -> CoinSpend:
        if coin.puzzle_hash != self.complete_puzzle_hash():
            raise ValueError("The Coin's puzzle hash does not match the generated puzzle hash.")
        coin_spend = CoinSpend(
            coin, self.complete_puzzle().to_serialized_program(), self.generate_solution().to_serialized_program()
        )
        try:
            coin_spend.additions()
        except Exception:
            raise ValueError("Invalid Puzzle or Puzzle Solutions")
        return coin_spend
