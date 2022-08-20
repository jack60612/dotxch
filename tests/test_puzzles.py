# import pytest
from secrets import token_bytes

import pytest
from blspy import AugSchemeMPL, PrivateKey
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.condition_tools import conditions_dict_for_solution, created_outputs_for_conditions_dict
from chia.util.keychain import mnemonic_to_seed
from chia_rs import Coin

from resolver.drivers.puzzle_drivers import DomainInnerPuzzle, DomainPuzzle, RegistrationFeePuzzle
from resolver.puzzles.puzzles import DOMAIN_PH_MOD, DOMAIN_PH_MOD_HASH, INNER_SINGLETON_MOD, REGISTRATION_FEE_MOD_HASH

seed = mnemonic_to_seed(
    "swarm fly ability pipe decide square involve caution tonight accuse weasel zero giant "
    "comfort sword brain sister want soccer mutual control question grass impact"
)
PRIVATE_KEY: PrivateKey = AugSchemeMPL.key_gen(seed)


class TestPuzzles:
    def test_domain_ph(self) -> None:
        domain_name = "jack.xch"
        correct_ph = "9783e069ef2c4b80e93619ae914b273d6c7f06c6d0c9e1ce66230390f9063cd3"
        assert DomainPuzzle(domain_name).complete_puzzle_hash().hex() == correct_ph

    def test_registration_fee(self) -> None:
        example_coin = Coin(DOMAIN_PH_MOD_HASH, REGISTRATION_FEE_MOD_HASH, 10000000001)
        domain_name = "jack.xch"
        reg_class = RegistrationFeePuzzle(
            domain_name, bytes32(b"6" * 32), bytes32(b"7" * 32), bytes32(b"8" * 32), bytes32(b"9" * 32)
        )
        cs = reg_class.to_coin_spend(example_coin)
        _, c_spend, _ = conditions_dict_for_solution(cs.puzzle_reveal, cs.solution, (1 << 32) - 1)
        assert c_spend is not None  # mypy
        r = created_outputs_for_conditions_dict(c_spend, example_coin.name())
        assert r[1].puzzle_hash == DOMAIN_PH_MOD.curry(domain_name).get_tree_hash()
        assert (
            reg_class.generate_solution().get_tree_hash().hex()
            == "0c281d6f403ea7101326ae78d6bc56203c5ef316e6cba08f84d9bf7fe59364dd"
        )

    @pytest.mark.asyncio
    async def test_inner_puzzle(self) -> None:
        domain_name = "jack.xch"
        pub_key = PRIVATE_KEY.get_g1()
        m_data = [("a", "a"), ("b", "b")]
        reg_class = DomainInnerPuzzle(
            DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            domain_name,
            pub_key,
            m_data,  # type: ignore[arg-type]
        )
        example_coin = Coin(DOMAIN_PH_MOD_HASH, reg_class.complete_puzzle_hash(), 1)
        with pytest.raises(ValueError):
            await reg_class.to_spend_bundle(AugSchemeMPL.key_gen(token_bytes(32)), example_coin, renew=True)

        sb = await reg_class.to_spend_bundle(PRIVATE_KEY, example_coin, renew=True)
        cs = sb.coin_spends[0]
        _, c_spend, _ = conditions_dict_for_solution(cs.puzzle_reveal, cs.solution, (1 << 32) - 1)
        assert c_spend is not None  # mypy
        r = created_outputs_for_conditions_dict(c_spend, example_coin.name())
        pre_puzzle = INNER_SINGLETON_MOD.curry(Program.to(domain_name))
        assert (
            r[0].puzzle_hash.hex()
            == pre_puzzle.curry(*[pre_puzzle.get_tree_hash(), pub_key, m_data]).get_tree_hash().hex()
        )
        assert (
            reg_class.generate_solution().get_tree_hash().hex()
            == "f46ffa082c9f3eee42d6d5ddf1d0e58ca1b13dc5fb008edbd432d4a0169ed45c"
        )
