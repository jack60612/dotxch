from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from aiohttp import ClientSession
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH

from resolver import __version__
from resolver.types.resolution_result import ResolutionResult

headers = {"Resolver-Version": str(__version__)}


@dataclass
class ResolverApiClient:
    chia_config: Dict[str, Any]
    chia_root: Path
    base_url: str
    aiohttp_session: ClientSession
    const_tuple: tuple[bytes, int]

    @classmethod
    def create_client(cls, hostname: str, port: int, chia_root: Path = DEFAULT_ROOT_PATH) -> "ResolverApiClient":
        config = load_config(chia_root, "config.yaml")
        overrides = config["network_overrides"]["constants"][config["selected_network"]]
        updated_constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
        const_tuple = (updated_constants.AGG_SIG_ME_ADDITIONAL_DATA, updated_constants.MAX_BLOCK_COST_CLVM)
        url = f"https://{hostname}:{str(port)}/"
        session = ClientSession(headers=headers)
        return cls(
            chia_config=config, chia_root=chia_root, base_url=url, aiohttp_session=session, const_tuple=const_tuple
        )

    async def close(self) -> None:
        await self.aiohttp_session.close()

    async def get(self, path: str) -> Dict[str, object]:
        async with self.aiohttp_session.get(self.base_url + path) as response:
            result: Dict[str, object] = await response.json()
            if "error" in result:
                await self.close()
                raise ValueError(result["error"])
            return result

    async def resolve(self, domain_name: str, launcher_id: Optional[bytes32] = None) -> ResolutionResult:
        l_id_query_str = f"&launcher_id=0x{launcher_id.hex()}" if launcher_id is not None else ""
        url = f"resolve?domain_name={domain_name}{l_id_query_str}"
        result = await self.get(url)
        return ResolutionResult.from_dict(result, self.const_tuple)
