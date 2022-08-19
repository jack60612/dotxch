# import pytest
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.condition_tools import conditions_dict_for_solution, created_outputs_for_conditions_dict
from chia_rs import Coin

from resolver.drivers.puzzle_drivers import DomainPuzzle, RegistrationFeePuzzle
from resolver.puzzles.puzzles import DOMAIN_PH_MOD, DOMAIN_PH_MOD_HASH, REGISTRATION_FEE_MOD, REGISTRATION_FEE_MOD_HASH


class TestPuzzles:
    def test_domain_ph(self):
        domain_name = "jack.xch"
        correct_ph = "9783e069ef2c4b80e93619ae914b273d6c7f06c6d0c9e1ce66230390f9063cd3"
        assert DomainPuzzle(domain_name).complete_puzzle_hash().hex() == correct_ph

    def test_registration(self):
        example_coin = Coin(DOMAIN_PH_MOD_HASH, REGISTRATION_FEE_MOD_HASH, 10000000001)
        domain_name = "jack.xch"
        reg_class = RegistrationFeePuzzle(domain_name, bytes32(b"6" * 32), bytes32(b"7" * 32), bytes32(b"8" * 32), bytes32(b"9" * 32))
        cs = reg_class.to_coin_spend(example_coin)
        _, c_spend, _ = conditions_dict_for_solution(
            cs.puzzle_reveal, cs.solution, (1 << 32) - 1
        )
        r = created_outputs_for_conditions_dict(c_spend, example_coin.name())
        assert r[1].puzzle_hash == DOMAIN_PH_MOD.curry(Program.to(domain_name)).get_tree_hash()
        assert reg_class.generate_solution().get_tree_hash().hex() == '0c281d6f403ea7101326ae78d6bc56203c5ef316e6cba08f84d9bf7fe59364dd'
