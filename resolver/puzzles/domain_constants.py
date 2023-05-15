from chia.types.blockchain_format.sized_bytes import bytes32

"""
This file should never be modified, it has the constants needed to generate puzzles.
This file also contains the registration address and things like that.
"""
year = 31556926  # year in seconds!
month = 2629743  # month in seconds!

REGISTRATION_FEE_AMOUNT = 10000000000
SINGLETON_AMOUNT = 1
TOTAL_FEE_AMOUNT = REGISTRATION_FEE_AMOUNT + SINGLETON_AMOUNT
TOTAL_NEW_DOMAIN_AMOUNT = TOTAL_FEE_AMOUNT + SINGLETON_AMOUNT
REGISTRATION_FEE_ADDRESS = bytes32.from_hexstr(
    "0xb0046b08ca25e28f947d1344b2ccc983be7fc8097a8f353cca43f2c54117a429"
)  # TODO:  (PLACEHOLDER) Change later.
REGISTRATION_LENGTH = year  # 1 year registration length
GRACE_PERIOD = month  # 1 month grace period
MAX_REGISTRATION_GAP = REGISTRATION_LENGTH + GRACE_PERIOD  # 1 year + 1 month
