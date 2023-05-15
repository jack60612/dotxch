from typing import Any

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.load_clvm import load_clvm

from resolver.puzzles.domain_constants import REGISTRATION_FEE_ADDRESS, REGISTRATION_FEE_AMOUNT, REGISTRATION_LENGTH


def load_clvm_wrapper(clvm_filename: Any) -> Program:
    return load_clvm(clvm_filename, __name__, include_standard_libraries=True)


# Load all puzzles from this directory in order of dependency & Initialize them with default values
DOMAIN_PH_MOD = load_clvm_wrapper("domain_ph.clsp").curry(REGISTRATION_LENGTH)
DOMAIN_PH_MOD_HASH = DOMAIN_PH_MOD.get_tree_hash()
REGISTRATION_FEE_MOD = load_clvm_wrapper("registration_fee.clsp").curry(
    DOMAIN_PH_MOD_HASH, REGISTRATION_FEE_ADDRESS, REGISTRATION_FEE_AMOUNT
)
REGISTRATION_FEE_MOD_HASH = REGISTRATION_FEE_MOD.get_tree_hash()
INNER_SINGLETON_MOD = load_clvm_wrapper("domain_inner.clsp").curry(REGISTRATION_FEE_MOD_HASH)
INNER_SINGLETON_MOD_HASH = INNER_SINGLETON_MOD.get_tree_hash()
