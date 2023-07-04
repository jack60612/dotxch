import asyncio
from pathlib import Path
from typing import Optional

import click
from chia.util.default_root import DEFAULT_ROOT_PATH, SIMULATOR_ROOT_PATH

from resolver.cmds.resolver_funcs import register, renew, resolve, transfer, update


@click.group()
@click.pass_context
@click.option("--root-path", type=click.Path(exists=True), default=DEFAULT_ROOT_PATH)
@click.option("--simulator", is_flag=True, default=False, hidden=True)
def resolver(ctx: click.Context, root_path: Path, simulator: bool) -> None:
    """
    This is the entry point for the resolver CLI.
    """
    ctx.ensure_object(dict)
    ctx.obj["root_path"] = root_path if not simulator else SIMULATOR_ROOT_PATH / "main"


# Node Only Commands
@resolver.command("resolve")
@click.pass_context
@click.option("-n", "--full-node-rpc-port", type=int, default=None)
@click.option("-d", "--domain-name", type=str, required=True)
@click.option("-l", "--launcher-id", type=str, default=None)
@click.option("-g", "--include-grace-period", is_flag=True, default=False)
def resolve_cmd(
    ctx: click.Context,
    full_node_rpc_port: Optional[int],
    domain_name: str,
    launcher_id: Optional[str],
    include_grace_period: bool,
) -> None:
    root_path = ctx.obj["root_path"]
    asyncio.run(resolve(root_path, full_node_rpc_port, domain_name, launcher_id, include_grace_period))


# Node & Wallet Commands
@resolver.command("register")
@click.pass_context
@click.option("-n", "--full-node-rpc-port", type=int, default=None)
@click.option("-r", "--wallet-rpc-port", type=int, default=None)
@click.option("-f", "--fingerprint", type=int, required=True)
@click.option("-w", "--wallet-id", type=int, required=True)
@click.option("-d", "--domain-name", type=str, required=True)
@click.option("-m", "--metadata", type=str, required=True)
@click.option("-p", "--fee", type=int, required=True)
@click.option("-s", "--skip_existing_check", is_flag=True, default=False)
def register_cmd(
    ctx: click.Context,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: str,
    fee: int,
    skip_existing_check: bool,
) -> None:
    root_path = ctx.obj["root_path"]
    asyncio.run(
        register(
            root_path,
            full_node_rpc_port,
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            domain_name,
            metadata,
            fee,
            skip_existing_check,
        )
    )


@resolver.command("renew")
@click.pass_context
@click.option("-n", "--full-node-rpc-port", type=int, default=None)
@click.option("-r", "--wallet-rpc-port", type=int, default=None)
@click.option("-f", "--fingerprint", type=int, required=True)
@click.option("-w", "--wallet-id", type=int, required=True)
@click.option("-d", "--domain-name", type=str, required=True)
@click.option("-m", "--metadata", type=str, default=None)
@click.option("-p", "--fee", type=int, required=True)
@click.option("-l", "--launcher-id", type=str, default=None)
def renew_cmd(
    ctx: click.Context,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: Optional[str],
    fee: int,
    launcher_id: Optional[str],
) -> None:
    root_path = ctx.obj["root_path"]
    asyncio.run(
        renew(
            root_path,
            full_node_rpc_port,
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            domain_name,
            metadata,
            fee,
            launcher_id,
        )
    )


@resolver.command("update")
@click.pass_context
@click.option("-n", "--full-node-rpc-port", type=int, default=None)
@click.option("-r", "--wallet-rpc-port", type=int, default=None)
@click.option("-f", "--fingerprint", type=int, required=True)
@click.option("-w", "--wallet-id", type=int, required=True)
@click.option("-d", "--domain-name", type=str, required=True)
@click.option("-m", "--metadata", type=str, required=True)
@click.option("-p", "--fee", type=int, required=True)
@click.option("-l", "--launcher-id", type=str, default=None)
def update_cmd(
    ctx: click.Context,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: str,
    fee: int,
    launcher_id: Optional[str],
) -> None:
    root_path = ctx.obj["root_path"]
    asyncio.run(
        update(
            root_path,
            full_node_rpc_port,
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            domain_name,
            metadata,
            fee,
            launcher_id,
        )
    )


@resolver.command("transfer")
@click.pass_context
@click.option("-n", "--full-node-rpc-port", type=int, default=None)
@click.option("-r", "--wallet-rpc-port", type=int, default=None)
@click.option("-f", "--fingerprint", type=int, required=True)
@click.option("-w", "--wallet-id", type=int, required=True)
@click.option("-d", "--domain-name", type=str, required=True)
@click.option("-m", "--metadata", type=str, required=True)
@click.option("-p", "--fee", type=int, required=True)
@click.option("-k", "--new-pubkey", type=str, required=True)
@click.option("-l", "--launcher-id", type=str, default=None)
def transfer_cmd(
    ctx: click.Context,
    full_node_rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    domain_name: str,
    metadata: str,
    new_pubkey: str,
    fee: int,
    launcher_id: Optional[str],
) -> None:
    root_path = ctx.obj["root_path"]
    asyncio.run(
        transfer(
            root_path,
            full_node_rpc_port,
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            domain_name,
            metadata,
            fee,
            new_pubkey,
            launcher_id,
        )
    )


if __name__ == "__main__":
    resolver()
