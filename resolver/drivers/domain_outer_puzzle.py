from typing import Any, Optional

from blspy import G2Element, PrivateKey
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.types.spend_bundle import SpendBundle
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD,
    SINGLETON_MOD_HASH,
    launch_conditions_and_coinsol,
    lineage_proof_for_coinsol,
    puzzle_for_singleton,
    solution_for_singleton,
)

from resolver.drivers.domain_inner_puzzle import DomainInnerPuzzle
from resolver.drivers.puzzle_class import BasePuzzle, PuzzleType, program_to_list, sign_coin_spend
from resolver.drivers.registration_fee_puzzle import RegistrationFeePuzzle
from resolver.puzzles.puzzles import INNER_SINGLETON_MOD, REGISTRATION_FEE_MOD_HASH


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
        self.launcher_id = launcher_id
        # This is: (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH)) & the inner puzzle
        curry_args = [(SINGLETON_MOD_HASH, (launcher_id, SINGLETON_LAUNCHER_HASH)), inner_puzzle.complete_puzzle()]
        # we will add the rest of the args below.
        solution_args = [self.lineage_proof.to_program()]
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

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend, const_tuple: tuple[bytes, int]) -> "DomainOuterPuzzle":
        sig_additional_data, max_block_cost = const_tuple
        try:
            new_coins: list[Coin] = compute_additions(coin_spend)
            assert len(new_coins) == 1
            new_coin: Coin = new_coins[0]
        except Exception:
            raise ValueError("Invalid CoinSpend")
        # first we receive and validate the puzzle and its first curried layer.
        base_puzzle, curried_args = coin_spend.puzzle_reveal.uncurry()
        if base_puzzle.get_tree_hash() != SINGLETON_MOD_HASH:
            raise ValueError("Incorrect Puzzle Driver")

        launcher_id = bytes32(curried_args.pair[0].pair[1].pair[0].atom)  # only outer uncurry.
        # uncurry inner puzzle.
        singleton_inner_puzzle = Program(curried_args.pair[1].pair[0])
        singleton_base_inner_puzzle, raw_inner_curry_args = singleton_inner_puzzle.uncurry()
        assert singleton_base_inner_puzzle.uncurry()[0] == INNER_SINGLETON_MOD  # sanity check
        domain_name = singleton_base_inner_puzzle.uncurry()[1].pair[0].atom.decode("utf-8")  # domain from puzzle.

        # now we extract the curried args from the inner puzzle.
        inner_curry_args = program_to_list(raw_inner_curry_args)
        pub_key = inner_curry_args[1]
        metadata = inner_curry_args[2]

        # we now process the coin_spend and get the potentially updated args.
        solution_program = coin_spend.solution.to_program()
        # first we select the inner sol, then we convert it into a list.
        _, _, sol_metadata, sol_pub_key = program_to_list(Program.to(solution_program.pair[1].pair[1].pair[0]))
        # now we replace the curried data with the data from the solution.
        pub_key = sol_pub_key if sol_pub_key else pub_key
        metadata = sol_metadata if sol_metadata else metadata
        inner_puzzle_class = DomainInnerPuzzle(domain_name, pub_key, metadata)
        # create a new lineage proof object.
        lineage_proof: LineageProof = LineageProof(
            new_coin.name(), singleton_inner_puzzle.get_tree_hash(), uint64(new_coin.amount)
        )
        return cls(sig_additional_data, max_block_cost, launcher_id, lineage_proof, inner_puzzle_class)

    @staticmethod
    async def create_singleton_from_inner(
        sig_additional_data: bytes,
        max_block_cost: int,
        private_key: PrivateKey,
        inner_puzzle: DomainInnerPuzzle,
        base_coin: Coin,
    ) -> tuple[list[Announcement], list[Announcement], list[dict[str, Any]], SpendBundle]:
        if not base_coin.amount >= 10000000002:
            # 10000000001 is for the fee ph, and 1 is for the singleton.
            raise ValueError("Base coin must be at least 1000000002 mojo's")
        # we create the singleton coin
        _, singleton_spend = launch_conditions_and_coinsol(
            base_coin, inner_puzzle.complete_puzzle(), inner_puzzle.cur_metadata, uint64(1)
        )
        # we create the spend bundle for the singleton
        singleton_spend_bundle = SpendBundle([singleton_spend], G2Element())
        singleton_coin = singleton_spend.coin
        domain_coin = compute_additions(singleton_spend)[0]
        lineage_proof = lineage_proof_for_coinsol(singleton_spend)  # initial lineage proof

        # create args for the inner puzzle renewal / creation spend.
        inner_puzzle.generate_solution_args(renew=True, coin=domain_coin)
        # now we create the domain full solution, coin spend & then a signed spend bundle
        # we wrap the coin spend in the singleton layer.
        domain_solution = SerializedProgram.from_program(
            solution_for_singleton(lineage_proof, uint64(1), inner_puzzle.generate_solution())
        )
        outer_puzzle_reveal = puzzle_for_singleton(singleton_coin.name(), inner_puzzle.complete_puzzle())
        domain_cs = CoinSpend(domain_coin, SerializedProgram.from_program(outer_puzzle_reveal), domain_solution)
        domain_spend_bundle = await sign_coin_spend(sig_additional_data, max_block_cost, domain_cs, private_key)

        # now we create the fee puzzle spend.
        assert inner_puzzle.domain_name is not None
        reg_fee_puzzle = RegistrationFeePuzzle(
            inner_puzzle.domain_name,
            outer_puzzle_reveal.get_tree_hash(),
            singleton_coin.name(),
            domain_coin.parent_coin_info,
        )
        fee_coin = Coin(base_coin.name(), REGISTRATION_FEE_MOD_HASH, 10000000001)
        fee_spend_bundle = await reg_fee_puzzle.to_spend_bundle(fee_coin)
        # for the launcher puzzle
        coin_assertions = [Announcement(singleton_coin.name(), singleton_spend.solution.get_tree_hash())]
        # for the registration_fee puzzle
        puzzle_assertions = [
            Announcement(
                REGISTRATION_FEE_MOD_HASH,
                bytes(std_hash(inner_puzzle.domain_name.encode() + domain_cs.coin.parent_coin_info)),
            )
        ]
        # fee ph, 1 for singleton
        primaries = [
            dict(amount=uint64(10000000001), puzzle_hash=REGISTRATION_FEE_MOD_HASH),
            dict(amount=uint64(1), puzzle_hash=SINGLETON_LAUNCHER_HASH),
        ]
        # add the bundles together to get the final bundle.
        spend_bundle = SpendBundle.aggregate([singleton_spend_bundle, domain_spend_bundle, fee_spend_bundle])
        return coin_assertions, puzzle_assertions, primaries, spend_bundle

    async def renew_domain(
        self,
        private_key: PrivateKey,
        domain_singleton: Coin,
        fee_coin: Coin,
        new_metadata: Optional[list[tuple[str, str]]] = None,
    ) -> tuple[list[Announcement], list[dict[str, Any]], SpendBundle]:
        # first we set inner puzzle to renew mode.
        self.domain_puzzle.generate_solution_args(renew=True, new_metadata=new_metadata, coin=domain_singleton)
        # now we generate a singleton renewal spend bundle.
        singleton_sb = await self.to_spend_bundle(private_key, domain_singleton)
        # now we generate the fee spend bundle.
        assert self.domain_name is not None
        reg_fee_puzzle = RegistrationFeePuzzle(
            self.domain_name,
            self.complete_puzzle_hash(),
            self.launcher_id,
            domain_singleton.parent_coin_info,
        )
        fee_coin = Coin(fee_coin.name(), REGISTRATION_FEE_MOD_HASH, 10000000001)
        fee_sb = await reg_fee_puzzle.to_spend_bundle(fee_coin)
        if self.lineage_proof.parent_name is None:
            raise ValueError("Cannot renew a domain that has never had an initial spend.")
        puzzle_assertions = [
            Announcement(
                REGISTRATION_FEE_MOD_HASH,
                bytes(std_hash(self.domain_name.encode() + domain_singleton.parent_coin_info)),
            )
        ]
        # fee ph, 1 for singleton
        primaries = [dict(amount=uint64(10000000001), puzzle_hash=REGISTRATION_FEE_MOD_HASH)]
        spend_bundle = SpendBundle.aggregate([singleton_sb, fee_sb])
        return puzzle_assertions, primaries, spend_bundle

    async def update_metadata(
        self,
        private_key: PrivateKey,
        domain_singleton: Coin,
        new_metadata: list[tuple[str, str]],
    ) -> tuple[list[Announcement], list[dict[str, Any]], SpendBundle]:
        assert self.domain_name is not None
        # first we set inner puzzle to change metadata.
        self.domain_puzzle.generate_solution_args(new_metadata=new_metadata, coin=domain_singleton)
        # now we get a singleton metadata update spend bundle.
        spend_bundle = await self.to_spend_bundle(private_key, domain_singleton)
        puzzle_assertions = [
            Announcement(
                self.complete_puzzle_hash(),
                bytes(std_hash(self.domain_name.encode() + domain_singleton.parent_coin_info)),
            )
        ]
        primaries = [dict(amount=uint64(0), puzzle_hash=REGISTRATION_FEE_MOD_HASH)]
        return puzzle_assertions, primaries, spend_bundle

    def to_coin_spend(self, coin: Coin) -> CoinSpend:
        if self.is_spendable_puzzle:
            self.solution_args = [self.solution_args[0]]  # regen args.
        self.solution_args.append(coin.amount)  # add coin amount and inner solution args.
        self.solution_args.append(self.domain_puzzle.generate_solution())
        return super().to_coin_spend(coin)

    async def to_spend_bundle(self, private_key: PrivateKey, coin: Coin) -> SpendBundle:
        if private_key.get_g1() != self.domain_puzzle.cur_pub_key:
            raise ValueError("Private key does not match public key")
        coin_spend = self.to_coin_spend(coin)
        return await sign_coin_spend(self.AGG_SIG_ME_ADDITIONAL_DATA, self.MAX_BLOCK_COST_CLVM, coin_spend, private_key)
