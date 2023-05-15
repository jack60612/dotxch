from typing import Any, Optional

from blspy import G1Element, G2Element, PrivateKey
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

from resolver.drivers.domain_inner_driver import DomainInnerPuzzle
from resolver.drivers.puzzle_class import BasePuzzle, DomainMetadata, PuzzleType, sign_coin_spend
from resolver.drivers.registration_fee_driver import RegistrationFeePuzzle
from resolver.puzzles.puzzles import REGISTRATION_FEE_MOD_HASH


async def _renew_domain(
    reg_fee_puzzle: RegistrationFeePuzzle, domain_singleton: Coin, parent_fee_coin_id: bytes32
) -> tuple[list[Announcement], list[dict[str, Any]], SpendBundle]:
    # now generate the fee spend bundle.
    fee_coin = Coin(parent_fee_coin_id, REGISTRATION_FEE_MOD_HASH, 10000000001)
    # resulting fee spend bundle.
    fee_sb: SpendBundle = await reg_fee_puzzle.to_spend_bundle(fee_coin)
    assert reg_fee_puzzle.domain_name is not None
    puzzle_assertions = [
        Announcement(
            REGISTRATION_FEE_MOD_HASH,
            bytes(std_hash(reg_fee_puzzle.domain_name.encode() + domain_singleton.parent_coin_info)),
        )
    ]

    # primaries are coins required for this spend bundle and the amount is fee + 1 for singleton.
    primaries = [dict(amount=uint64(10000000001), puzzle_hash=REGISTRATION_FEE_MOD_HASH)]
    return puzzle_assertions, primaries, fee_sb


class DomainOuterPuzzle(BasePuzzle):
    def __init__(
        self,
        sig_additional_data: bytes,
        max_block_cost: int,
        launcher_id: bytes32,
        lineage_proof: LineageProof,
        inner_puzzle: DomainInnerPuzzle,
    ):
        self.domain_puzzle: DomainInnerPuzzle = inner_puzzle
        self.lineage_proof: LineageProof = lineage_proof
        self.launcher_id: bytes32 = launcher_id
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
        except Exception:
            raise ValueError("Invalid CoinSpend")
        # first we receive and validate the puzzle and its first curried layer.
        base_puzzle, curried_args = coin_spend.puzzle_reveal.uncurry()
        if base_puzzle.get_tree_hash() != SINGLETON_MOD_HASH:
            raise ValueError("Incorrect Puzzle Driver")

        # [MOD_HASH, LAUNCHER_ID, LAUNCHER_PUZZLE_HASH], INNER_PUZZLE
        singleton_struct, singleton_inner_puzzle = list(curried_args.as_iter())
        launcher_id = bytes32(singleton_struct.as_python()[1])  # only outer uncurry.

        # we now get the inner solution and generate the inner coin spend.
        inner_solution = Program(coin_spend.solution.to_program().pair[1].pair[1].pair[0])
        inner_cs: CoinSpend = CoinSpend(coin_spend.coin, singleton_inner_puzzle, inner_solution)

        inner_puzzle_class = DomainInnerPuzzle.from_coin_spend(inner_cs)

        # create a new lineage proof object, this is used to generate the parent coin info.
        # essentially: (parent_coin.parent_coin_id, parents_inner_puz_hash, parent_coin.amount)
        lineage_proof: LineageProof = LineageProof(
            coin_spend.coin.parent_coin_info, singleton_inner_puzzle.get_tree_hash(), uint64(coin_spend.coin.amount)
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
        _, launcher_spend = launch_conditions_and_coinsol(
            base_coin, inner_puzzle.complete_puzzle(), inner_puzzle.cur_metadata, uint64(1)
        )
        launcher_coin = launcher_spend.coin  # the first child of the base coin.
        # we create the spend bundle to create the singleton coin from the launcher.
        launcher_spend_bundle = SpendBundle([launcher_spend], G2Element())
        # we get the resulting coin from the launcher and its lineage proof.
        domain_singleton = compute_additions(launcher_spend)[0]  # 2nd child of the base coin, (it's a singleton now)
        lineage_proof = lineage_proof_for_coinsol(launcher_spend)  # initial lineage proof

        # create args for the inner puzzle renewal / creation spend.
        inner_puzzle.generate_solution_args(renew=True, coin=domain_singleton)
        # now we create the domain full solution, coin spend & then a signed spend bundle
        # we wrap the coin spend in the singleton layer.
        domain_singleton_solution = SerializedProgram.from_program(
            solution_for_singleton(lineage_proof, uint64(1), inner_puzzle.generate_solution())
        )
        outer_puzzle_reveal = puzzle_for_singleton(launcher_coin.name(), inner_puzzle.complete_puzzle())
        domain_cs = CoinSpend(
            domain_singleton, SerializedProgram.from_program(outer_puzzle_reveal), domain_singleton_solution
        )
        domain_spend_bundle = await sign_coin_spend(sig_additional_data, max_block_cost, domain_cs, private_key)

        # now we create the fee puzzle spend / renewal.
        assert inner_puzzle.domain_name is not None
        reg_fee_puzzle = RegistrationFeePuzzle(
            inner_puzzle.domain_name,
            outer_puzzle_reveal.get_tree_hash(),
            launcher_coin.name(),
            domain_singleton.parent_coin_info,
        )
        puzzle_assertions, fee_primaries, fee_spend_bundle = await _renew_domain(
            reg_fee_puzzle, domain_singleton, base_coin.name()
        )
        # fee ph, 1 for singleton
        primaries = [dict(amount=uint64(1), puzzle_hash=SINGLETON_LAUNCHER_HASH)] + fee_primaries
        # for the launcher puzzle
        coin_assertions = [Announcement(launcher_coin.name(), launcher_spend.solution.get_tree_hash())]
        # add the bundles together to get the final bundle.
        combined_spend_bundle = SpendBundle.aggregate([launcher_spend_bundle, domain_spend_bundle, fee_spend_bundle])
        return coin_assertions, puzzle_assertions, primaries, combined_spend_bundle

    async def renew_domain(
        self,
        private_key: PrivateKey,
        domain_singleton: Coin,
        parent_fee_coin: Coin,
        new_metadata: Optional[DomainMetadata] = None,
    ) -> tuple[list[Announcement], list[dict[str, Any]], SpendBundle]:
        if self.lineage_proof.parent_name is None:
            raise ValueError("Cannot renew a domain that has never had an initial spend.")

        # Generate singleton renewal spend bundle.
        self.domain_puzzle.generate_solution_args(renew=True, new_metadata=new_metadata, coin=domain_singleton)
        singleton_sb: SpendBundle = await self.to_spend_bundle(private_key, domain_singleton)

        assert self.domain_name is not None
        # get resulting fee spend bundle.
        reg_fee_puzzle = RegistrationFeePuzzle(
            self.domain_name,
            self.complete_puzzle_hash(),
            self.launcher_id,
            domain_singleton.parent_coin_info,
        )
        puzzle_assertions, primaries, fee_sb = await _renew_domain(
            reg_fee_puzzle, domain_singleton, parent_fee_coin.name()
        )
        # Combine the two spend bundles.
        combined_spend_bundle: SpendBundle = SpendBundle.aggregate([singleton_sb, fee_sb])
        return puzzle_assertions, primaries, combined_spend_bundle

    async def update_metadata(
        self,
        private_key: PrivateKey,
        domain_singleton: Coin,
        new_metadata: DomainMetadata,
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

    async def update_pubkey(
        self,
        private_key: PrivateKey,
        domain_singleton: Coin,
        new_metadata: DomainMetadata,
        new_pubkey: G1Element,
    ) -> tuple[list[Announcement], list[dict[str, Any]], SpendBundle]:
        assert self.domain_name is not None
        # first we set inner puzzle to change metadata and pubkey.
        self.domain_puzzle.generate_solution_args(
            new_metadata=new_metadata, new_pubkey=new_pubkey, coin=domain_singleton
        )
        # now we get a singleton metadata update spend bundle.
        spend_bundle = await self.to_spend_bundle(private_key, domain_singleton)

        puzzle_assertions = [  # this is if we want to bundle a fee with the pubkey update.
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
