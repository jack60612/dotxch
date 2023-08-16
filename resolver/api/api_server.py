# import necessary packages
import asyncio
import datetime
import logging
from asyncio import CancelledError
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aiohttp import web
from aiohttp.web_request import Request
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.default_root import DEFAULT_ROOT_PATH, SIMULATOR_ROOT_PATH
from chia.util.ints import uint16

from resolver import __version__
from resolver.core.client_funcs import NodeClient, process_domain_name

# setup logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, encoding="utf-8")


headers = {"Resolver-Version": str(__version__), "Cache-Control": "max-age=120"}


class FIFODictCache:
    max_size: int
    dict: OrderedDict[str, Dict[str, object]]
    key_time_list: List[Tuple[str, datetime.datetime]]
    cleanup_task: asyncio.Task[None]

    def __init__(self, max_size: int = 500) -> None:
        self.max_size = max_size
        self.dict = OrderedDict()
        self.key_time_list: List[Tuple[str, datetime.datetime]] = []
        self.cleanup_task = asyncio.create_task(self.cleanup())

    def __setitem__(self, key: str, value: Dict[str, object]) -> None:
        if key not in self.dict:
            if len(self.dict) >= self.max_size:
                self.dict.popitem(last=False)
        self.dict[key] = value
        self.key_time_list.append((key, datetime.datetime.now()))

    def __getitem__(self, key: str) -> Dict[str, object]:
        return self.dict[key]

    async def stop(self) -> None:
        self.cleanup_task.cancel()
        try:
            await self.cleanup_task
        except CancelledError:  # ignore task cancellation
            pass

    async def cleanup(self) -> None:
        while True:
            # get current time
            now = datetime.datetime.now()
            # loop through key_time_list
            for key, time in self.key_time_list:
                # check if time is older than 5 minutes
                if (now - time).total_seconds() > 300:
                    # remove item from dict
                    self.dict.pop(key)
                    # remove item from key_time_list
                    self.key_time_list.remove((key, time))
            # sleep for 5 minutes
            await asyncio.sleep(300)

    def get(self, key: str) -> Optional[Dict[str, object]]:
        return self.dict.get(key)


@dataclass
class ApiServer:
    app: web.Application
    node_client: NodeClient
    fifo_cache: FIFODictCache

    @classmethod
    def create(cls, chia_root: Path, rpc_port: Optional[uint16] = None) -> "ApiServer":
        # create node_client
        node_client = NodeClient(root_path=chia_root, rpc_port=rpc_port)
        # setup aiohttp app
        app = web.Application()
        # create new class
        new_cls = cls(app=app, node_client=node_client, fifo_cache=FIFODictCache())
        # finish setup
        new_cls.app.add_routes(new_cls.routes())
        new_cls.app.on_shutdown.append(new_cls.stop)
        return new_cls

    @property
    def config(self) -> Dict[str, object]:
        return self.node_client.config

    async def start(self) -> None:
        await self.node_client.start()

    async def stop(self, _app: web.Application) -> None:
        await self.node_client.stop()
        await self.fifo_cache.stop()

    def routes(self) -> List[web.RouteDef]:
        return [
            web.get("/", self.hello),
            web.get("/resolve", self.resolve_domain),
        ]

    async def hello(self, request: web.Request) -> web.Response:
        return web.Response(text="Success!", headers=headers)

    async def resolve_domain(self, request: Request) -> web.Response:
        # get domain name
        domain_name = request.query.get("domain_name")
        if domain_name is None or domain_name == "":
            return web.json_response({"error": "No domain name provided"}, status=400)
        try:
            domain_name = process_domain_name(str(domain_name))
        except ValueError as e:
            return web.json_response({"error": e.args[0]}, status=400)

        # get launcher id
        launcher_id_hex = request.query.get("launcher_id")
        l_id_bytes = None
        if launcher_id_hex is not None:  # we bypass cache if launcher id is provided
            try:
                l_id_bytes = bytes32.fromhex(launcher_id_hex)
            except ValueError:
                return web.json_response({"error": "Invalid launcher id"}, status=400)
        else:
            # check if the domain name is in the cache.
            cache_result = self.fifo_cache.get(domain_name)
            if cache_result is not None:
                return web.json_response(cache_result, headers=headers)

        # get dict resolution record
        res_result = (await self.node_client.resolve_domain(domain_name, l_id_bytes)).to_dict()

        # cache result
        if launcher_id_hex is None:
            self.fifo_cache[domain_name] = res_result

        # return domain record
        return web.json_response(res_result, headers={"Cache-Control": "max-age=120"})


async def create_web_app() -> web.Application:
    testing = False
    # set root
    c_root = DEFAULT_ROOT_PATH
    if testing:
        c_root = SIMULATOR_ROOT_PATH / "main"
    # initalize class & web app
    api_server = ApiServer.create(chia_root=c_root)
    # start
    await api_server.start()
    return api_server.app


# main
if __name__ == "__main__":
    web.run_app(create_web_app(), host=["::0", "0.0.0.0"], port=80)
