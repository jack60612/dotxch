from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Tuple, Union

from blspy import G1Element, PrivateKey
from chia.cmds.units import units
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint64
from yaml import dump, safe_load

from resolver.core.client_funcs import NodeClient, WalletClient
from resolver.puzzles.domain_constants import TOTAL_FEE_AMOUNT, TOTAL_NEW_DOMAIN_AMOUNT
from resolver.types.domain_metadata import DomainMetadata, DomainMetadataDict
from resolver.types.domain_record import DomainRecord
from resolver.types.resolution_result import ResolutionResult
from resolver.types.resolution_status_code import ResolutionStatusCode


@asynccontextmanager
async def get_node_client(
    rpc_port: Optional[int] = None, root_path: Path = DEFAULT_ROOT_PATH
) -> AsyncIterator[Tuple[NodeClient, Dict[str, Any]]]:
    config = load_config(root_path, "config.yaml")
    if rpc_port is None:
        rpc_port = config["full_node"]["rpc_port"]
    node_client = NodeClient(config, root_path, uint16(rpc_port))
    await node_client.start()
    try:
        assert node_client.client is not None
        await node_client.client.healthz()  # test connection
        yield node_client, config
    finally:
        await node_client.stop()


@asynccontextmanager
async def get_wallet_and_node_client(
    fingerprint: int,
    wallet_rpc_port: Optional[int] = None,
    full_node_rpc_port: Optional[int] = None,
    root_path: Path = DEFAULT_ROOT_PATH,
) -> AsyncIterator[Tuple[WalletClient, Dict[str, Any]]]:
    async with get_node_client(rpc_port=full_node_rpc_port, root_path=root_path) as (node_client, config):
        if wallet_rpc_port is None:
            wallet_rpc_port = config["wallet"]["rpc_port"]
        wallet_client = WalletClient(node_client, config, root_path, uint16(wallet_rpc_port))
        try:
            await wallet_client.start(fingerprint)
            yield wallet_client, config
        finally:
            await wallet_client.stop()


def timestamp_to_human(timestamp: Union[uint64, int, float]) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def xch_fee_to_mojo(xch_fee: Decimal) -> uint64:
    return uint64(xch_fee * units["chia"])


def yaml_to_dict(yaml_metadata: str) -> dict[str, Any]:
    """Loads a file or string containing YAML metadata."""
    if yaml_metadata.endswith(".yaml") or yaml_metadata.endswith(".yml"):
        with open(yaml_metadata, "r") as f:
            return DomainMetadataDict(safe_load(f))
    return DomainMetadataDict(safe_load(yaml_metadata))


def yaml_to_metadata(yaml_metadata: str) -> DomainMetadata:
    """Loads a file or string containing YAML metadata and returns a DomainMetadata object."""
    meta_dict = DomainMetadataDict(yaml_to_dict(yaml_metadata))
    return DomainMetadata.from_dict(meta_dict)


def print_domain_record(domain_record: DomainRecord, print_metadata: bool = False) -> None:
    print("Domain information:\n")
    print(f"Domain name: {domain_record.domain_name}")
    print(f"Public key: 0x{domain_record.domain_class.domain_puzzle.cur_pub_key.__bytes__().hex()}")
    print(f"Launcher ID: 0x{domain_record.launcher_id.hex()}\n\n")

    print("Registration information:\n")
    print(f" Created at: {timestamp_to_human(domain_record.creation_timestamp)}")
    print(f" Expires at: {timestamp_to_human(domain_record.expiration_timestamp)}")
    print(f" Last renewal was at block: {domain_record.registration_update_height}\n\n")

    if print_metadata:
        print("Metadata information:")
        print(f"\n{dump(domain_record.domain_metadata.to_dict())}")
        print(f"Last Metadata update was at block: {domain_record.state_update_height}")


async def resolve(
    root_path: Path, rpc_port: Optional[int], domain_name: str, launcher_id: Optional[str], include_grace_period: bool
) -> None:
    async with get_node_client(rpc_port=rpc_port, root_path=root_path) as (node_client, config):
        launcher_id_hex: Optional[bytes32] = None
        if launcher_id is not None:
            launcher_id_hex = bytes32.fromhex(launcher_id)
        result: ResolutionResult = await node_client.resolve_domain(domain_name, launcher_id_hex, include_grace_period)
        if result.status_code == ResolutionStatusCode.NOT_FOUND:
            print("Domain not resolved")
            return
        elif result.status_code == ResolutionStatusCode.CONFLICTING:
            print("WARNING!!! Domain has conflicting records and is INVALID!\n\n")
        elif result.status_code == ResolutionStatusCode.EXPIRED:
            print("WARNING!!! Domain has expired.\n\n")
        elif result.status_code == ResolutionStatusCode.GRACE_PERIOD:
            print("WARNING!!! Domain is in grace period and is about to expire.\n\n")
        elif result.status_code == ResolutionStatusCode.LATEST:
            print("Domain resolved")
        else:
            raise ValueError(f"Unexpected status code: {result.status_code}")
        domain_record = result.domain_record
        assert domain_record is not None  # cant be None if status_code is not NOT_FOUND
        print_domain_record(domain_record, print_metadata=True)


async def register(
    root_path: Path,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: DomainMetadata,
    fee: uint64,
    skip_existing_check: bool,
) -> None:
    async with get_wallet_and_node_client(fingerprint, wallet_rpc_port, full_node_rpc_port, root_path) as (
        wallet_client,
        config,
    ):
        if (
            input(
                f"The Total cost to register this domain is "
                f"{(fee + TOTAL_NEW_DOMAIN_AMOUNT) / units['chia']} XCH. Continue? (Y/N) "
            ).lower()
            != "y"
        ):
            print("Aborted")
            return
        pub_key = None
        fee_tx, sb = await wallet_client.create_domain(
            wallet_id=wallet_id,
            domain_name=domain_name,
            metadata=metadata,
            fee=fee,
            skip_existing_check=skip_existing_check,
            pub_key=pub_key,
        )
        wallet_tx_id = fee_tx.name
        print(f"Successfully created domain {domain_name}, total fee amount {fee_tx.amount / units['chia']} XCH")
        print(f"Fee Transaction ID: 0x{wallet_tx_id}")
        print(f"Spend Bundle ID: {sb.name()}")
        print(
            f"It might be a while before this transaction is confirmed. "
            f"Run 'chia wallet get_transaction -f {fingerprint} -tx 0x{wallet_tx_id}' to get status"
        )


async def renew(
    root_path: Path,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: Optional[DomainMetadata],
    fee: uint64,
    launcher_id: Optional[str],
    private_key: Optional[PrivateKey] = None,
) -> None:
    async with get_wallet_and_node_client(fingerprint, wallet_rpc_port, full_node_rpc_port, root_path) as (
        wallet_client,
        config,
    ):
        if (
            input(
                f"The Total cost to renew this domain is "
                f"{(fee + TOTAL_FEE_AMOUNT) / units['chia']} XCH. Continue? (Y/N) "
            ).lower()
            != "y"
        ):
            print("Aborted")
            return
        launcher_id_hex: Optional[bytes32] = None
        if launcher_id is not None:
            launcher_id_hex = bytes32.fromhex(launcher_id)

        # attempt to resolve the domain to check if it exists
        cur_record = await wallet_client.node_client.resolve_domain(domain_name, launcher_id_hex, grace_period=True)
        if cur_record.domain_record is None:
            raise ValueError(f"Domain {domain_name} does not exist.")
        if (
            cur_record.status_code != ResolutionStatusCode.LATEST
            and cur_record.status_code != ResolutionStatusCode.GRACE_PERIOD
        ):
            raise ValueError(
                f"Domain {domain_name} is not in a state where it can be renewed, "
                f"its current status code is: {cur_record.status_code}."
            )
        if input("Would you like to continue with this renewal? (Y/N) ").lower() != "y":
            print("Aborted")
            return

        fee_tx, sb = await wallet_client.renew_domain(
            domain_record=cur_record.domain_record,
            wallet_id=wallet_id,
            fee=fee,
            new_metadata=metadata,
            private_key=private_key,
        )
        wallet_tx_id = fee_tx.name
        print(f"Successfully renewed domain {domain_name}, total final fee amount {fee_tx.amount / units['chia']} XCH")
        print(f"Fee Transaction ID: 0x{wallet_tx_id}")
        print(f"Spend Bundle ID: {sb.name()}")
        print(
            f"It might be a while before this transaction is confirmed. "
            f"Run 'chia wallet get_transaction -f {fingerprint} -tx 0x{wallet_tx_id}' to get status"
        )


async def update(
    root_path: Path,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: DomainMetadata,
    fee: uint64,
    launcher_id: Optional[str],
    private_key: Optional[PrivateKey] = None,
) -> None:
    async with get_wallet_and_node_client(fingerprint, wallet_rpc_port, full_node_rpc_port, root_path) as (
        wallet_client,
        config,
    ):
        launcher_id_hex: Optional[bytes32] = None
        if launcher_id is not None:
            launcher_id_hex = bytes32.fromhex(launcher_id)

        # attempt to resolve the domain to check if it exists
        cur_record = await wallet_client.node_client.resolve_domain(domain_name, launcher_id_hex, grace_period=False)
        if cur_record.domain_record is None:
            raise ValueError(f"Domain {domain_name} does not exist.")
        if cur_record.status_code != ResolutionStatusCode.LATEST:
            raise ValueError(
                f"Domain {domain_name} is not in a state where it can be updated, "
                f"its current status code is: {cur_record.status_code}."
            )
        if input("Would you like to continue with this metadata update? (Y/N) ").lower() != "y":
            print("Aborted")
            return

        fee_tx, sb = await wallet_client.update_metadata(
            domain_record=cur_record.domain_record, fee=fee, new_metadata=metadata, private_key=private_key
        )
        fee_tx_amt = fee_tx.amount / units["chia"] if fee_tx is not None else 0
        print(f"Successfully updated domain {domain_name}, total final fee amount {fee_tx_amt} XCH")
        print(f"Spend Bundle ID: {sb.name()}")
        if fee_tx is not None:
            wallet_tx_id = fee_tx.name
            print(f"Fee Transaction ID: 0x{wallet_tx_id}")
            print(
                f"It might be a while before this transaction is confirmed. "
                f"Run 'chia wallet get_transaction -f {fingerprint} -tx 0x{wallet_tx_id}' to get status"
            )
        else:
            print("No fee transaction was created, since the fee amount was 0.")
            print("You can check if the coin was spent on a blockchain explorer")


async def transfer(
    root_path: Path,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: DomainMetadata,
    fee: uint64,
    new_pubkey_str: str,
    launcher_id: Optional[str],
    private_key: Optional[PrivateKey] = None,
) -> None:
    async with get_wallet_and_node_client(fingerprint, wallet_rpc_port, full_node_rpc_port, root_path) as (
        wallet_client,
        config,
    ):
        launcher_id_hex: Optional[bytes32] = None
        if launcher_id is not None:
            launcher_id_hex = bytes32.fromhex(launcher_id)
        new_pubkey = G1Element.from_bytes(hexstr_to_bytes(new_pubkey_str))

        # attempt to resolve the domain to check if it exists
        cur_record = await wallet_client.node_client.resolve_domain(domain_name, launcher_id_hex, grace_period=False)
        if cur_record.domain_record is None:
            raise ValueError(f"Domain {domain_name} does not exist.")
        if cur_record.status_code != ResolutionStatusCode.LATEST:
            raise ValueError(
                f"Domain {domain_name} is not in a state where it can be transferred, "
                f"its current status code is: {cur_record.status_code}."
            )
        if input("Would you like to continue with this domain transfer? (Y/N) ").lower() != "y":
            print("Aborted")
            return

        fee_tx, sb = await wallet_client.update_pubkey(
            domain_record=cur_record.domain_record,
            fee=fee,
            new_metadata=metadata,
            new_pubkey=new_pubkey,
            private_key=private_key,
        )
        fee_tx_amt = fee_tx.amount / units["chia"] if fee_tx is not None else 0
        print(f"Successfully transferred domain {domain_name}, total final fee amount {fee_tx_amt} XCH")
        print(f"Spend Bundle ID: {sb.name()}")
        if fee_tx is not None:
            wallet_tx_id = fee_tx.name
            print(f"Fee Transaction ID: 0x{wallet_tx_id}")
            print(
                f"It might be a while before this transaction is confirmed. "
                f"Run 'chia wallet get_transaction -f {fingerprint} -tx 0x{wallet_tx_id}' to get status"
            )
        else:
            print("No fee transaction was created, since the fee amount was 0.")
            print("You can check if the coin was spent on a blockchain explorer")
