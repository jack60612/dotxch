# import pytest
from secrets import token_bytes

import pytest
from blspy import AugSchemeMPL, PrivateKey
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.announcement import Announcement
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash
from chia.util.keychain import mnemonic_to_seed
from chia_rs import Coin

from resolver.drivers.domain_driver import DomainPuzzle
from resolver.drivers.domain_inner_driver import DomainInnerPuzzle
from resolver.drivers.domain_outer_driver import DomainOuterPuzzle
from resolver.drivers.registration_fee_driver import RegistrationFeePuzzle
from resolver.puzzles.domain_constants import REGISTRATION_FEE_ADDRESS
from resolver.puzzles.puzzles import DOMAIN_PH_MOD, DOMAIN_PH_MOD_HASH, INNER_SINGLETON_MOD, REGISTRATION_FEE_MOD_HASH
from resolver.types.domain_metadata import DomainMetadataRaw

seed = mnemonic_to_seed(
    "swarm fly ability pipe decide square involve caution tonight accuse weasel zero giant "
    "comfort sword brain sister want soccer mutual control question grass impact"
)
PRIVATE_KEY: PrivateKey = AugSchemeMPL.key_gen(seed)


class TestPuzzles:
    def test_domain_ph(self) -> None:
        domain_name = "jack.xch"
        correct_ph = bytes32.from_hexstr("343026ae53f5de0bf5d9e041aeda6d05cff53f23cb2494868e73bf7c330f4fdd")
        example_coin = Coin(REGISTRATION_FEE_MOD_HASH, correct_ph, 1)
        dp_class = DomainPuzzle(domain_name=domain_name)
        assert dp_class.complete_puzzle_hash() == correct_ph
        cs = dp_class.to_coin_spend(example_coin)
        assert compute_additions(cs) == []  # No additions / new coins
        cs_bytes = hexstr_to_bytes(
            "69c71a85585f938c7b8a45a35d167bf022023a4605a42de0b2346e502f9992e5343026ae53f5de0bf5d9"
            "e041aeda6d05cff53f23cb2494868e73bf7c330f4fdd0000000000000001ff02ffff01ff02ffff01ff02"
            "ffff01ff04ffff04ff0cffff04ff05ff808080ffff04ffff04ff08ffff01ff018080ffff04ffff04ff0a"
            "ffff04ffff0bff0b80ff808080ffff04ffff04ff0effff01ff018080ff8080808080ffff04ffff01ffff"
            "4950ff3c34ff018080ffff04ffff018401e1853eff018080ffff04ffff01886a61636b2e786368ff0180"
            "8001"
        )
        assert domain_name == DomainPuzzle.from_coin_spend(CoinSpend.from_bytes(cs_bytes)).domain_name

    def test_registration_fee(self) -> None:
        example_coin = Coin(DOMAIN_PH_MOD_HASH, REGISTRATION_FEE_MOD_HASH, 10000000001)
        domain_name = "jack.xch"
        reg_class = RegistrationFeePuzzle(
            domain_name=domain_name,
            domain_outer_ph=bytes32(b"6" * 32),
            singleton_launcher_id=bytes32(b"7" * 32),
            singleton_parent_id=bytes32(b"8" * 32),
        )
        cs = reg_class.to_coin_spend(example_coin)
        r = compute_additions(cs)
        assert r[1].puzzle_hash == DOMAIN_PH_MOD.curry(domain_name).get_tree_hash()
        assert (
            reg_class.generate_solution().get_tree_hash().hex()
            == "4c5b390267209459068d94383ac0bfecb2666206038ca0ea00fde94b775ec53b"
        )
        cs_bytes = hexstr_to_bytes(
            "989379ca2baa34863789a365b20764bd6aae0b7c72f5dca9de6ca1cf132d5abe7bb18ebcdbee14e01c44110f46c439bc96d155406e39a0adc3b21b41d49c79a200000002540be401ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff2fffff04ff5fffff04ff81bfffff04ffff0bff2fff82017f80ff80808080808080808080ffff04ffff01ffffff3f02ff33ff3e04ffff01ff0102ffff02ffff03ff05ffff01ff02ff16ffff04ff02ffff04ff0dffff04ffff0bff3affff0bff12ff3c80ffff0bff3affff0bff3affff0bff12ff2a80ff0980ffff0bff3aff0bffff0bff12ff8080808080ff8080808080ffff010b80ff0180ffff0bff3affff0bff12ff1880ffff0bff3affff0bff3affff0bff12ff2a80ff0580ffff0bff3affff02ff16ffff04ff02ffff04ff07ffff04ffff0bff12ff1280ff8080808080ffff0bff12ff8080808080ff04ffff04ff10ffff04ffff0bff5fff82017f80ff808080ffff04ffff04ff2cffff04ff82017fff808080ffff04ffff04ff14ffff04ff0bffff04ff17ff80808080ffff04ffff04ff14ffff04ffff02ff2effff04ff02ffff04ff05ffff04ffff0bffff0101ff2f80ff8080808080ffff04ffff0101ffff04ffff04ff81bfff8080ff8080808080ff8080808080ff018080ffff04ffff01a0989379ca2baa34863789a365b20764bd6aae0b7c72f5dca9de6ca1cf132d5abeffff04ffff01a0b0046b08ca25e28f947d1344b2ccc983be7fc8097a8f353cca43f2c54117a429ffff04ffff018502540be400ff0180808080ff886a61636b2e786368ffa03636363636363636363636363636363636363636363636363636363636363636ffa03737373737373737373737373737373737373737373737373737373737373737ffa0383838383838383838383838383838383838383838383838383838383838383880"  # noqa: E501
        )
        assert domain_name == RegistrationFeePuzzle.from_coin_spend(CoinSpend.from_bytes(cs_bytes)).domain_name

    @pytest.mark.asyncio
    async def test_inner_puzzle(self) -> None:
        domain_name = "jack.xch"
        pub_key = PRIVATE_KEY.get_g1()
        m_data = DomainMetadataRaw([("a", b"a"), ("b", b"b")])
        inner_puz_class = DomainInnerPuzzle(
            domain_name=domain_name,
            cur_pub_key=pub_key,
            cur_metadata=m_data,
        )
        example_coin = Coin(DOMAIN_PH_MOD_HASH, inner_puz_class.complete_puzzle_hash(), 1)
        inner_puz_class.generate_solution_args(
            coin=example_coin, renew=True, new_metadata=DomainMetadataRaw(m_data * 2)
        )
        with pytest.raises(NotImplementedError):
            await inner_puz_class.to_spend_bundle(AugSchemeMPL.key_gen(token_bytes(32)), example_coin)

        cs = inner_puz_class.to_coin_spend(example_coin)
        r = compute_additions(cs)
        pre_puzzle = INNER_SINGLETON_MOD.curry(Program.to(domain_name))
        assert (
            r[0].puzzle_hash.hex()
            == pre_puzzle.curry(*[pre_puzzle.get_tree_hash(), pub_key, m_data * 2]).get_tree_hash().hex()
        )
        assert (
            inner_puz_class.generate_solution().get_tree_hash().hex()
            == "1368f8a77e7cab0e257a77c235b25efadfe78e25f37691cb84755efaa2436658"
        )
        regen_inner_puz = DomainInnerPuzzle.from_coin_spend(cs)
        assert domain_name == regen_inner_puz.domain_name
        assert m_data != regen_inner_puz.cur_metadata

    @pytest.mark.asyncio
    async def test_outer_puzzle(self) -> None:
        domain_name = "jack.xch"
        pub_key = PRIVATE_KEY.get_g1()
        m_data = DomainMetadataRaw([("a", b"a"), ("b", b"b")])
        inner_puz_class = DomainInnerPuzzle(
            domain_name=domain_name,
            cur_pub_key=pub_key,
            cur_metadata=m_data,
        )
        example_coin = Coin(DOMAIN_PH_MOD_HASH, inner_puz_class.complete_puzzle_hash(), 10000000002)
        inner_puz_class.generate_solution_args(coin=example_coin, renew=True)
        # Validate inner coin_spend.
        assert domain_name == DomainInnerPuzzle.from_coin_spend(inner_puz_class.to_coin_spend(example_coin)).domain_name
        # Test outer puzzle
        (
            coin_assertions,
            puzzle_assertions,
            primaries,
            spend_bundle,
        ) = await DomainOuterPuzzle.create_singleton_from_inner(
            DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            PRIVATE_KEY,
            inner_puz_class,
            example_coin,
        )
        const_tuple = (DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA, DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM)
        outer_class = DomainOuterPuzzle.from_outer_coin_spend(spend_bundle.coin_spends[1], const_tuple)
        example_outer_coin = Coin(DOMAIN_PH_MOD_HASH, outer_class.complete_puzzle_hash(), 1)
        outer_class.domain_puzzle.generate_solution_args(
            renew=True, new_metadata=DomainMetadataRaw([("bruh", b"bruh")]), coin=example_outer_coin
        )
        # validate announcements
        assert puzzle_assertions == [
            Announcement(
                REGISTRATION_FEE_MOD_HASH,
                bytes(std_hash(bytes(domain_name.encode() + spend_bundle.coin_spends[1].coin.parent_coin_info))),
            )
        ]
        assert coin_assertions == [
            Announcement(spend_bundle.coin_spends[0].coin.name(), spend_bundle.coin_spends[0].solution.get_tree_hash())
        ]
        # check spend bundle
        non_eph_adds = spend_bundle.not_ephemeral_additions()
        assert len(non_eph_adds) == 3
        assert REGISTRATION_FEE_ADDRESS in [coin.puzzle_hash for coin in non_eph_adds]
        assert DomainPuzzle(domain_name=domain_name).complete_puzzle_hash() in [
            coin.puzzle_hash for coin in non_eph_adds
        ]
        working_outer_class = DomainOuterPuzzle.from_outer_coin_spend(
            outer_class.to_coin_spend(example_outer_coin), const_tuple
        )
        assert working_outer_class.domain_name == domain_name
        assert working_outer_class.puzzle_mod == outer_class.puzzle_mod
        assert working_outer_class.launcher_id == outer_class.launcher_id
        assert working_outer_class.domain_puzzle.cur_metadata == [("bruh", b"bruh")]
