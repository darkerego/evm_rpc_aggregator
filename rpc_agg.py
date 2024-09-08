import argparse
import ast
import itertools
import os
import pprint
import re
from time import time
import requests
import web3
import websockets
from web3 import Web3
import dotenv
from web3.exceptions import ExtraDataLengthError
from operator import itemgetter
from web3.middleware import ExtraDataToPOAMiddleware

dotenv.load_dotenv()


class Timer:
    def __init__(self, name: str = None):
        self.name = name if name is not None else 'timer_'+str(time())
        self.start = time()
        self.end = 0
        self.elapsed = 0

    def stop(self):
        self.end = time()
        self.elapsed = time() - self.start
        return self.elapsed


class ChainRPCIterator:

    def __init__(self, chain_id: int, verbosity: int = 0):
        """
        Initialize the ChainRPCIterator with the chain_id and protocol type.

        :param chain_id: Integer ID of the blockchain.
        :param protocol: Either "http" or "ws" to filter the RPCs by protocol type.
        """
        dotenv.load_dotenv()
        self.verbose = bool(verbosity)
        self.INFURA_API_KEY = os.getenv("INFURA_API_KEY")
        # print(self.INFURA_API_KEY)
        self.chain_id = chain_id
        # self.protocol = protocol
        self.rpc_list = self._get_rpcs('http')
        self.ws_list = self._get_rpcs('ws')
        self.index = 0
        self.initialized_http_list: list[web3.Web3] = []
        self.initialized_ws_list: list[web3.Web3] = []
        self.http_cycler: itertools.cycle | None = None
        self.ws_cycler: itertools.cycle | None = None
        self.results = {}


    def _get_rpcs(self, protocol='http'):
        """
        Fetches the chain data and filters the RPC URLs by chain_id and protocol.

        :return: A list of RPC URLs that match the given chain_id and protocol.
        """
        url = "https://chainid.network/chains_mini.json"
        response = requests.get(url)

        if response.status_code != 200:
            raise ValueError("Failed to fetch chain data.")

        chains = response.json()

        for chain in chains:
            if chain.get('chainId') == self.chain_id:
                if self.verbose:
                    print(chain)
                # Filter RPC URLs by protocol (either "http" or "ws")
                return [rpc for rpc in chain.get('rpc', []) if rpc.startswith(protocol)]

        return []

    def __iter__(self):
        return self

    def __next__(self):
        """
        Return the next RPC URL in the list, or raise StopIteration if done.
        """
        if self.index < len(self.rpc_list):
            rpc = self.rpc_list[self.index]
            self.index += 1
            return rpc
        else:
            raise StopIteration

    def time_rpc(self, w3_instance: web3.Web3, endpoint: str) -> tuple[str, float]:
        t = Timer(endpoint)
        blocks = w3_instance.eth.get_block('latest', True)
        assert blocks is not None
        elapsed = t.stop()
        return endpoint, elapsed


    def test_poa_chain(self, ins: web3.Web3) -> bool:
        try:
            ins.eth.get_block('latest', True)
        except ExtraDataLengthError:
            return True
        return False


    def get_web3_instances(self, protocol='http', as_cycler: bool = False):
        """
        Initializes and returns a list of web3.Web3 instances for the RPC URLs.

        :return: A list of initialized Web3 instances.
        """
        web3_instances = []

        rpc_time_map_http = {}
        rpc_time_map_ws = {}
        if protocol == 'http':
            for rpc in self.rpc_list:
                # print(rpc)
                if rpc is not None:
                    if re.findall(r'INFURA_API_KEY', rpc):
                        rpc = rpc.replace('${INFURA_API_KEY}', self.INFURA_API_KEY)
                        # print('rpc', rpc)
                    if protocol == "http":
                        web3_instance = Web3(Web3.HTTPProvider(rpc))
                        if web3_instance.is_connected():
                            if self.test_poa_chain(web3_instance):
                                web3_instance.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                            ep, run_time = self.time_rpc(web3_instance, rpc)
                            rpc_time_map_http.update({ep: run_time})
                            web3_instances.append(web3_instance)
                            self.initialized_http_list.append(web3_instance)
                        else:
                            if self.verbose:
                                print(f"Warning: Unable to connect to RPC {rpc}")
        else:
            for rpc in self.ws_list:
                if rpc is not None:
                    if re.findall(r'INFURA_API_KEY', rpc):
                        rpc = rpc.replace('${INFURA_API_KEY}', self.INFURA_API_KEY)
                        if self.verbose:
                            print('rpc', rpc)

                    if protocol == "ws":
                        web3_instance = Web3(Web3.LegacyWebSocketProvider(rpc))
                        try:
                            if web3_instance.is_connected():
                                if self.test_poa_chain(web3_instance):
                                    web3_instance.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                                    ep, run_time = self.time_rpc(web3_instance, rpc)
                                    rpc_time_map_ws.update({ep: run_time})

                                web3_instances.append(web3_instance)
                                self.initialized_ws_list.append(web3_instance)
                            else:
                                if self.verbose:
                                    print(f"Warning: Unable to connect to RPC {rpc}")
                        except (websockets.exceptions.InvalidStatusCode,websockets.exceptions.ConnectionClosedError) as err:
                            if self.verbose:
                                print(f"Warning: Unable to connect to RPC {rpc}: {err}")
                        else:
                            continue

        if protocol == 'http':
            self.results = rpc_time_map_http
            cyc = self.http_cycler = itertools.cycle(self.initialized_http_list)
            lst = self.initialized_http_list
        else:
            self.results = rpc_time_map_ws
            cyc = self.ws_cycler = itertools.cycle(self.initialized_ws_list)
            lst = self.initialized_ws_list

        if as_cycler:
            return cyc
        else:
            return lst

    @property
    def time_maps(self):
        return sorted(self.results.items(), key=itemgetter(1), reverse=True)


def get_rpc_cycler(chain_id, protocol):
    """
    Creates an iterator for RPCs based on the chain ID and protocol type.

    :param chain_id: Integer ID of the blockchain.
    :param protocol: Either "http" or "ws".
    :return: An iterator that provides RPC URLs.
    """
    if protocol not in ["http", "ws"]:
        raise ValueError("Invalid protocol. Must be 'http' or 'ws'.")

    return ChainRPCIterator(chain_id).get_web3_instances(protocol)

if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument("chain_id",  type=int, help="The chain ID.")
    args.add_argument("protocol",  type=str, help="Either 'http' or 'ws'.")
    args.add_argument('-v', '--verbose', action='count', default=0)
    subparsers = args.add_subparsers(dest='command')
    timer = subparsers.add_parser('timer')
    tester = subparsers.add_parser('tester')

    args = args.parse_args()
    dotenv.load_dotenv()
    if args.command == 'tester':
        w3s = ChainRPCIterator(args.chain_id, args.verbose).get_web3_instances(args.protocol)
        print([r for r in w3s])
    else:
        cri = ChainRPCIterator(args.chain_id)
        w3s = cri.get_web3_instances(args.protocol, args.verbose)
        times = cri.time_maps
        pprint.pp(times)
