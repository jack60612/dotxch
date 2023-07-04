from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Tuple

from blspy import G1Element
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16

from resolver.core.client_funcs import NodeClient, WalletClient
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
        print(f"Domain name: {result.domain_name}")
        print(f"Raw domain record: {result.domain_record}")


async def register(
    root_path: Path,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: str,
    fee: int,
    skip_existing_check: bool,
) -> None:
    async with get_wallet_and_node_client(fingerprint, wallet_rpc_port, full_node_rpc_port, root_path) as (
        wallet_client,
        config,
    ):
        ...


async def renew(
    root_path: Path,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: Optional[str],
    fee: int,
    launcher_id: Optional[str],
) -> None:
    async with get_wallet_and_node_client(fingerprint, wallet_rpc_port, full_node_rpc_port, root_path) as (
        wallet_client,
        config,
    ):
        launcher_id_hex: Optional[bytes32] = None
        if launcher_id is not None:
            launcher_id_hex = bytes32.fromhex(launcher_id)
        pass


async def update(
    root_path: Path,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: str,
    fee: int,
    launcher_id: Optional[str],
) -> None:
    async with get_wallet_and_node_client(fingerprint, wallet_rpc_port, full_node_rpc_port, root_path) as (
        wallet_client,
        config,
    ):
        launcher_id_hex: Optional[bytes32] = None
        if launcher_id is not None:
            launcher_id_hex = bytes32.fromhex(launcher_id)
        pass


async def transfer(
    root_path: Path,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: str,
    fee: int,
    new_pubkey_str: str,
    launcher_id: Optional[str],
) -> None:
    async with get_wallet_and_node_client(fingerprint, wallet_rpc_port, full_node_rpc_port, root_path) as (
        wallet_client,
        config,
    ):
        launcher_id_hex: Optional[bytes32] = None
        if launcher_id is not None:
            launcher_id_hex = bytes32.fromhex(launcher_id)
        new_pubkey = G1Element.from_bytes(bytes.fromhex(new_pubkey_str))
        pass
