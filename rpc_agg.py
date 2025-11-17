#/usr/bin/env python3
#####################################
# Evm RPC Aggregator & Execution Timer
# Darkerego ~ 2024 ~ tips ~ 0xDA2De7d401833bD1Ae658f38E2FFaF2e08E440a9
######################################
import argparse
import asyncio
import itertools
import os
import pprint
import re
import sys
from time import time

import requests
import web3.eth
from aiohttp import ClientResponseError, ClientConnectorDNSError, ClientSession
from eth_utils import to_checksum_address
from web3 import Web3, AsyncWeb3, AsyncHTTPProvider, WebSocketProvider
import dotenv
from web3.exceptions import ExtraDataLengthError, ProviderConnectionError, Web3RPCError
from operator import itemgetter
from web3.middleware import ExtraDataToPOAMiddleware

dotenv.load_dotenv()


class Timer:
    def __init__(self, name: str | None = None):
        self.name = name if name is not None else "timer_" + str(time())
        self.start = time()
        self.end = 0.0
        self.elapsed = 0.0

    def stop(self) -> float:
        self.end = time()
        self.elapsed = self.end - self.start
        return self.elapsed


class ChainRPCIterator:
    def __init__(
        self,
        chain_id: int,
        async_instances: bool = True,
        verbosity: int = 0,
        protocol: str | None = None,
    ):
        """
        Initialize the ChainRPCIterator with the chain_id and protocol type.

        :param chain_id: Integer ID of the blockchain.
        :param protocol: Either "http" or "ws" to filter the RPCs by protocol type.
        """
        dotenv.load_dotenv()
        self.protocols = protocol if protocol is not None else "http"
        self.verbose = bool(verbosity)
        self.INFURA_API_KEY = os.getenv("INFURA_API_KEY")
        self.chain_id = chain_id
        # async by default
        self._async = async_instances

        self.index = 0
        # These store endpoint URIs, not Web3 objects
        self.initialized_http_list: list[str] = []
        self.initialized_ws_list: list[str] = []
        self.http_cycler: itertools.cycle | None = None
        self.ws_cycler: itertools.cycle | None = None
        self.results: dict[str, float] = {}

        self.chain_data: list[dict] = self.get_chain_data()
        self.rpc_list = self._get_rpcs("http")
        self.ws_list = self._get_rpcs("ws")

        # Shared aiohttp session for AsyncHTTPProvider to avoid
        # unclosed ClientSession warnings
        self._aiohttp_session: ClientSession | None = None

    async def _ensure_aiohttp_session(self) -> None:
        if self._aiohttp_session is None:
            self._aiohttp_session = ClientSession()

    async def aclose(self) -> None:
        """Explicitly close any shared async resources (aiohttp session)."""
        if self._aiohttp_session is not None:
            await self._aiohttp_session.close()
            self._aiohttp_session = None

    def get_chain_data(self) -> list[dict]:
        """
        Fetches the chain data JSON from chainid.network.

        :return: List of chain info dicts.
        """
        url = "https://chainid.network/chains_mini.json"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            raise ValueError("Failed to fetch chain data.")
        return response.json()

    def _get_rpcs(self, protocol: str = "http") -> list[str]:
        """
        Filters the chain data down to RPC URLs for this chain_id and protocol.

        :param protocol: "http" or "ws"
        :return: List of RPC URLs that match the given chain_id and protocol.
        """
        for chain in self.chain_data:
            if chain.get("chainId") == self.chain_id:
                if self.verbose:
                    print(chain)
                return [
                    rpc for rpc in chain.get("rpc", []) if rpc.startswith(protocol)
                ]
        return []

    def __iter__(self):
        return self

    def __next__(self) -> str:
        """Return the next HTTP RPC URL in the list, or raise StopIteration if done."""
        if self.index < len(self.rpc_list):
            rpc = self.rpc_list[self.index]
            self.index += 1
            return rpc
        raise StopIteration

    async def time_rpc(
        self,
        w3_instance: web3.Web3 | AsyncWeb3,
        endpoint: str,
        quick_mode: bool = False,
    ) -> tuple[str | None, float]:
        """
        Time a few basic RPC calls against the given endpoint.

        Returns (endpoint, elapsed_seconds) on success, or (None, 0.0) on error.
        """
        timer = Timer(endpoint)
        blocks = None
        cid = None
        gas_price = None

        try:
            if not quick_mode:
                if self._async:
                    assert isinstance(w3_instance, AsyncWeb3)
                    cid = await w3_instance.eth.chain_id
                    blocks = await w3_instance.eth.get_block("latest", True)
                    await w3_instance.eth.get_balance(
                        to_checksum_address("0x" + "0" * 40)
                    )
                    await w3_instance.eth.fee_history(5, "latest", [10, 20, 30])
                    gas_price = await w3_instance.eth.gas_price
                else:
                    assert isinstance(w3_instance, Web3)
                    w3_instance.eth.get_balance(
                        to_checksum_address("0x" + "0" * 40)
                    )
                    w3_instance.eth.fee_history(5, "latest", [10, 20, 30])
                    blocks = w3_instance.eth.get_block("latest", True)
                    cid = w3_instance.eth.chain_id
                    gas_price = w3_instance.eth.gas_price

                if int(cid) != int(self.chain_id):
                    raise AssertionError(
                        f"Expected chain_id {self.chain_id}, got {cid} for {endpoint}"
                    )
                if int(gas_price) <= 0:
                    raise ValueError("Invalid gas price received!")
            else:
                if self._async:
                    assert isinstance(w3_instance, AsyncWeb3)
                    cid = await w3_instance.eth.chain_id
                else:
                    assert isinstance(w3_instance, Web3)
                    cid = w3_instance.eth.chain_id

                if int(cid) != int(self.chain_id):
                    raise AssertionError(
                        f"Expected chain_id {self.chain_id}, got {cid} for {endpoint}"
                    )

        except AssertionError:
            if self.verbose:
                print(f"[!] WARNING: endpoint {endpoint} is on the wrong chain!")
            return None, 0.0
        except ValueError as err:
            if self.verbose:
                print(
                    f"Nonsensical data returned from endpoint: {endpoint}, error: {err}"
                )
            return None, 0.0
        except (ClientConnectorDNSError, ClientResponseError, Web3RPCError) as err:
            if self.verbose:
                print(f"[!] RPC error for endpoint {endpoint}: {err}")
            return None, 0.0
        except Exception as err:
            if self.verbose:
                print(f"Error with endpoint: {endpoint} , error: {err}")
            return None, 0.0

        elapsed = timer.stop()

        if not quick_mode and blocks is None:
            if self.verbose:
                print(f"[!] No block data for endpoint {endpoint} despite no error.")
            return None, elapsed

        return endpoint, elapsed

    async def test_poa_chain(self, ins: web3.Web3 | AsyncWeb3) -> bool | None:
        """
        Checks sync and async web3.

        Returns:
            True  -> POA chain (middleware needed)
            False -> Not POA
            None  -> Wrong chain / error
        """
        try:
            if self._async:
                assert isinstance(ins, AsyncWeb3)
                cid = await ins.eth.chain_id
            else:
                assert isinstance(ins, Web3)
                cid = ins.eth.chain_id

            if int(cid) != int(self.chain_id):
                return None

            if self._async:
                await ins.eth.get_block("latest", True)
            else:
                ins.eth.get_block("latest", True)

        except ExtraDataLengthError:
            return True
        except (Web3RPCError, AssertionError, Exception):
            return None

        return False

    async def _test_http_rpc_async(
        self,
        rpc: str,
        quick_mode: bool,
        rpc_time_map_http: dict[str, float],
        semaphore: asyncio.Semaphore,
    ) -> None:
        """
        Worker to test a single HTTP RPC asynchronously with concurrency limiting.
        """
        async with semaphore:
            if not rpc or "flashbots" in rpc:
                return

            if "INFURA_API_KEY" in rpc:
                rpc = rpc.replace("${INFURA_API_KEY}", self.INFURA_API_KEY or "")

            await self._ensure_aiohttp_session()
            web3_instance = AsyncWeb3(AsyncHTTPProvider(rpc))
            # Reuse shared session to avoid unclosed ClientSession warnings
            await web3_instance.provider.cache_async_session(self._aiohttp_session)

            test_ok_poa = await self.test_poa_chain(web3_instance)
            if test_ok_poa is None:
                return
            if test_ok_poa:
                web3_instance.middleware_onion.inject(
                    ExtraDataToPOAMiddleware, layer=0
                )

            try:
                if self.verbose:
                    print(f"Running time test for {rpc}")
                ep, run_time = await self.time_rpc(web3_instance, rpc, quick_mode)
                if ep:
                    rpc_time_map_http[ep] = run_time
                    self.initialized_http_list.append(ep)
            except Exception as err:
                if self.verbose:
                    print(f"[!] Exception encountered for {rpc}: {err}")

    async def _test_ws_rpc_async(
        self,
        rpc: str,
        quick_mode: bool,
        rpc_time_map_ws: dict[str, float],
        semaphore: asyncio.Semaphore,
    ) -> None:
        """
        Worker to test a single WS RPC asynchronously with concurrency limiting.
        Ensures the WebSocket connection is properly disconnected to avoid
        pending tasks when the loop closes.
        """
        async with semaphore:
            if not rpc:
                return

            if "INFURA_API_KEY" in rpc:
                rpc = rpc.replace("${INFURA_API_KEY}", self.INFURA_API_KEY or "")

            web3_instance = AsyncWeb3(WebSocketProvider(rpc))

            try:
                await web3_instance.provider.connect()
                test_ok_poa = await self.test_poa_chain(web3_instance)
                if test_ok_poa:
                    web3_instance.middleware_onion.inject(
                        ExtraDataToPOAMiddleware, layer=0
                    )

                if await web3_instance.eth.chain_id <= 0:
                    return

                ep, run_time = await self.time_rpc(web3_instance, rpc, quick_mode)
                if ep:
                    rpc_time_map_ws[ep] = run_time
                    if self.verbose:
                        print(f"Adding {rpc} to list")
                    self.initialized_ws_list.append(ep)
            except ProviderConnectionError as err:
                if self.verbose:
                    print(f"[!] Cannot async connect encountered: {err}")
            except Exception as err:
                if self.verbose:
                    print(f"[!] WS exception for {rpc}: {err}")
            finally:
                # Explicitly disconnect to avoid leftover websocket tasks
                try:
                    await web3_instance.provider.disconnect()
                except Exception as err:
                    if self.verbose:
                        print(f"[!] Error during WS disconnect for {rpc}: {err}")

    async def get_web3_instances(
        self,
        protocol: str = "http",
        as_cycler: bool = False,
        quick_mode: bool = False,
        max_concurrency: int = 5,
    ):
        """
        Initializes and returns a list/cycler of RPC endpoints for the given protocol.

        The actual Web3/AsyncWeb3 instances are used transiently to test RPCs,
        but what this returns (and what self.http_cycler/ws_cycler iterate) are
        endpoint strings, ordered by availability and timing.
        """
        sync_web3_instances: list[Web3] = []
        rpc_time_map_http: dict[str, float] = {}
        rpc_time_map_ws: dict[str, float] = {}

        if protocol == "http":
            if not self._async:
                # sync HTTP path
                for rpc in self.rpc_list:
                    if not rpc or "flashbots" in rpc:
                        continue

                    if "INFURA_API_KEY" in rpc:
                        rpc = rpc.replace("${INFURA_API_KEY}", self.INFURA_API_KEY or "")

                    web3_instance = Web3(Web3.HTTPProvider(rpc))
                    if hasattr(web3_instance, "is_connected") and not web3_instance.is_connected():
                        continue

                    test_ok_poa = await self.test_poa_chain(web3_instance)
                    if test_ok_poa is None:
                        continue
                    if test_ok_poa:
                        web3_instance.middleware_onion.inject(
                            ExtraDataToPOAMiddleware, layer=0
                        )

                    ep, run_time = await self.time_rpc(web3_instance, rpc, quick_mode)
                    if ep:
                        rpc_time_map_http[ep] = run_time
                        self.initialized_http_list.append(ep)
                        sync_web3_instances.append(web3_instance)
            else:
                # async HTTP path with concurrency control
                semaphore = asyncio.Semaphore(max_concurrency)
                tasks: list[asyncio.Task] = []
                for rpc in self.rpc_list:
                    task = asyncio.create_task(
                        self._test_http_rpc_async(
                            rpc,
                            quick_mode,
                            rpc_time_map_http,
                            semaphore,
                        )
                    )
                    tasks.append(task)
                if tasks:
                    await asyncio.gather(*tasks)

        else:
            # WebSocket protocol
            if not self._async:
                # sync WS path
                for rpc in self.ws_list:
                    if not rpc:
                        continue

                    if "INFURA_API_KEY" in rpc:
                        rpc = rpc.replace("${INFURA_API_KEY}", self.INFURA_API_KEY or "")

                    if self.verbose:
                        print("Testing: sync", rpc)
                    web3_instance = Web3(Web3.LegacyWebSocketProvider(rpc))

                    test_ok_poa = await self.test_poa_chain(web3_instance)
                    if test_ok_poa:
                        web3_instance.middleware_onion.inject(
                            ExtraDataToPOAMiddleware, layer=0
                        )

                    if hasattr(web3_instance, "is_connected") and not web3_instance.is_connected():
                        continue

                    ep, run_time = await self.time_rpc(web3_instance, rpc, quick_mode)
                    if ep:
                        rpc_time_map_ws[ep] = run_time
                        sync_web3_instances.append(web3_instance)
                        self.initialized_ws_list.append(ep)
            else:
                # async WS path with concurrency control
                semaphore = asyncio.Semaphore(max_concurrency)
                tasks: list[asyncio.Task] = []
                for rpc in self.ws_list:
                    task = asyncio.create_task(
                        self._test_ws_rpc_async(
                            rpc,
                            quick_mode,
                            rpc_time_map_ws,
                            semaphore,
                        )
                    )
                    tasks.append(task)
                if tasks:
                    await asyncio.gather(*tasks)

        if "http" in self.protocols and protocol == "http":
            self.results = rpc_time_map_http
            self.http_cycler = itertools.cycle(self.initialized_http_list)
            if as_cycler:
                return self.http_cycler
            return self.initialized_http_list

        if "ws" in self.protocols and protocol == "ws":
            self.results = rpc_time_map_ws
            self.ws_cycler = itertools.cycle(self.initialized_ws_list)
            if as_cycler:
                return self.ws_cycler
            return self.initialized_ws_list

        return None

    @property
    def time_maps(self):
        return sorted(self.results.items(), key=itemgetter(1), reverse=True)


async def get_rpc_cycler(chain_id: int, protocol: str, max_concurrency: int = 5):
    """Creates an iterator (or list) for RPCs based on the chain ID and protocol type."""
    if protocol not in ["http", "ws"]:
        raise ValueError("Invalid protocol. Must be 'http' or 'ws'.")

    cri = ChainRPCIterator(chain_id, async_instances=True, verbosity=0, protocol=protocol)
    endpoints = await cri.get_web3_instances(protocol, max_concurrency=max_concurrency)
    await cri.aclose()
    return endpoints


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        usage=(
            f"\nExample: python3 {sys.argv[0]} 1 http  # get http rpc's for ETH"
            f"\nExample: python3 {sys.argv[0]} 56 ws   # get ws rpc's for BSC \n"
        ),
        description="Tool to aggregate, test, and determine the latency of EVM rpc's",
    )
    parser.add_argument("chain_id", type=int, help="The chain ID.")
    parser.add_argument("protocol", type=str, help="Either 'http', 'ws', or 'all'")
    parser.add_argument(
        "-a",
        "--async",
        dest="async_w3",
        action="store_true",
        default=True,
        help="Use AsyncWeb3 (default: async enabled).",
    )
    parser.add_argument(
        "-s",
        "--sync",
        dest="async_w3",
        action="store_false",
        help="Force sync Web3 instances.",
    )
    parser.add_argument(
        "-q",
        "--quick",
        action="store_true",
        help="Disable extensive testing (not recommended for quality, but faster).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable asyncio debug logging",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=10,
        help="Maximum number of concurrent async RPC tests (default: 5).",
    )

    args = parser.parse_args()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Only show asyncio debug logs if -d/--debug is passed
    loop.set_debug(bool(args.debug))
    dotenv.load_dotenv()

    cri = ChainRPCIterator(args.chain_id, args.async_w3, args.verbose, args.protocol)
    try:
        w3_endpoints = loop.run_until_complete(
            cri.get_web3_instances(
                args.protocol,
                as_cycler=False,
                quick_mode=args.quick,
                max_concurrency=args.max_concurrency,
            )
        )
        times = cri.time_maps
        pprint.pp(times)
    finally:
        loop.run_until_complete(cri.aclose())
        loop.close()
