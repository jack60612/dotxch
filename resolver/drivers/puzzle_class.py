from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from blspy import G1Element, PrivateKey
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.sign_coin_spends import sign_coin_spends
from clvm.SExp import CastableType

from resolver.puzzles.puzzles import REGISTRATION_FEE_MOD_HASH


class PuzzleType(Enum):
    DOMAIN = 0
    FEE = 1
    INNER = 2
    OUTER = 3


def program_to_list(program: Program) -> list[Any]:
    """
    This is a helper function to convert a Program to a list of arguments, which were taken from the curry args of a
    puzzle or directly from a puzzle solution. This function just converts bytes to the correct class.
    :param program:
    :return: A list of program arguments, in python classes.
    """
    n_list: list[Any] = []
    for item in program.as_python():
        if isinstance(item, bytes):
            if len(item) == 32:
                n_list.append(bytes32(item))
            elif len(item) == 48:  # public key
                n_list.append(G1Element.from_bytes(item))
            # Now we convert the bool types
            elif item.hex() == "01":
                n_list.append(True)
            elif item.hex() == "":  # what 80 gets converted to
                n_list.append(False)
            else:
                n_list.append(item)
        else:
            n_list.append(item)
    return n_list


def validate_initial_spend(coin_spend: Optional[CoinSpend]) -> Optional[bytes32]:
    """
    This function validates that the initial spend is valid & returns the launcher id.
    :param coin_spend: CoinSpend object that created domain coin.
    :return: LauncherID if valid, None if invalid.
    """
    if coin_spend is not None and coin_spend.coin.puzzle_hash == REGISTRATION_FEE_MOD_HASH:
        _, result = coin_spend.puzzle_reveal.run_with_cost(INFINITE_COST, coin_spend.solution)
        for condition in result.as_python():
            if condition[0] == ConditionOpcode.CREATE_COIN and len(condition) >= 4:
                # If only 3 elements (opcode + 2 args), there is no memo, this is ph, amount
                if type(condition[3]) != list:
                    # If it's not a list, it's not the correct format
                    continue
                return bytes32(condition[3][0])
    return None


async def sign_coin_spend(
    agg_sig_me_additional_data: bytes, max_block_cost_clvm: int, coin_spend: CoinSpend, private_key: PrivateKey
) -> SpendBundle:
    async def priv_key(pk: G1Element) -> PrivateKey:
        return private_key

    return await sign_coin_spends(
        [coin_spend],
        priv_key,
        agg_sig_me_additional_data,
        max_block_cost_clvm,
    )


def program_to_lineage_proof(program: Program) -> LineageProof:
    python_program = program_to_list(program)
    parent_name: bytes32 = python_program[0]
    inner_ph: Optional[bytes32] = None
    if len(python_program) == 3:
        inner_ph = python_program[1]
        amount: uint64 = python_program[2]
    else:
        amount = python_program[1]
    return LineageProof(parent_name, inner_ph, amount)


@dataclass(kw_only=True)
class BasePuzzle:
    puzzle_type: PuzzleType
    raw_puzzle: Program
    puzzle_mod: bytes32
    num_curry_args: int
    num_solution_args: int
    curry_args: list[CastableType] = field(default_factory=list)
    solution_args: list[CastableType] = field(default_factory=list)
    domain_name: Optional[str] = field(default=None)

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend, puzzle_type: PuzzleType) -> "BasePuzzle":
        try:
            compute_additions(coin_spend)
        except Exception:
            raise ValueError("Invalid CoinSpend")
        solution_args = program_to_list(coin_spend.solution.to_program())

        if puzzle_type == PuzzleType.FEE:
            base_puzzle = coin_spend.puzzle_reveal.to_program()
            domain_name = solution_args[0]
            curried_args = []
        else:
            base_puzzle, raw_curried_args = coin_spend.puzzle_reveal.uncurry()
            curried_args = program_to_list(raw_curried_args)
            if puzzle_type == PuzzleType.DOMAIN:
                domain_name = curried_args[0]
            elif puzzle_type == PuzzleType.INNER:
                domain_name = base_puzzle.uncurry()[1].as_python()[0]
            else:
                raise ValueError("Invalid Puzzle Type")
        return BasePuzzle(
            puzzle_type=puzzle_type,
            raw_puzzle=base_puzzle,
            puzzle_mod=base_puzzle.get_tree_hash(),
            num_curry_args=len(curried_args),
            num_solution_args=len(solution_args),
            curry_args=curried_args,
            solution_args=solution_args,
            domain_name=domain_name.decode("utf-8"),
        )

    @property
    def is_complete_puzzle(self) -> bool:
        return len(self.curry_args) == self.num_curry_args

    @property
    def is_spendable_puzzle(self) -> bool:
        return len(self.solution_args) == self.num_solution_args

    def complete_puzzle(self) -> Program:
        if not self.is_complete_puzzle:
            raise ValueError("Puzzle is missing or has too many curry arguments.")
        if self.num_curry_args != 0:
            return self.raw_puzzle.curry(*self.curry_args)
        else:
            return self.raw_puzzle

    def complete_puzzle_hash(self) -> bytes32:
        return self.complete_puzzle().get_tree_hash()

    def generate_solution(self) -> Program:
        if not self.is_spendable_puzzle:
            raise ValueError("Puzzle is missing or has too many solution arguments.")
        if self.num_solution_args > 1:
            result: Program = Program.to(self.solution_args)
        elif self.num_solution_args == 0:
            result = Program.to(1)  # Anything works here
        else:
            result = Program.to(self.solution_args[0])
        return result

    def to_coin_spend(self, coin: Coin) -> CoinSpend:
        if coin.puzzle_hash != self.complete_puzzle_hash():
            raise ValueError("The Coin's puzzle hash does not match the generated puzzle hash.")
        coin_spend = CoinSpend(
            coin,
            SerializedProgram.from_program(self.complete_puzzle()),
            SerializedProgram.from_program(self.generate_solution()),
        )
        try:
            compute_additions(coin_spend)
        except Exception:
            raise ValueError("Invalid Puzzle or Puzzle Solutions")
        return coin_spend
