# evm_rpc_aggregator
Find the fastest pubic rpcs via chainlist.org

### About


<pre>
 python3 rpc_lib.py 1 http  -q -h
usage: 
Example: python3 rpc_lib.py 1 http  # get http rpc's for ETH
Example: python3 rpc_lib.py 56 ws   # get ws rpc's for BSC 

Tool to aggregate, test, and determine the latency of EVM rpc's

positional arguments:
  chain_id              The chain ID.
  protocol              Either 'http', 'ws', or 'all'

options:
  -h, --help            show this help message and exit
  -a, --async           Use AsyncWeb3 (default: async enabled).
  -s, --sync            Force sync Web3 instances.
  -q, --quick           Disable extensive testing (not recommended for quality, but faster).
  -v, --verbose
  -d, --debug           Enable asyncio debug logging
  --max-concurrency MAX_CONCURRENCY
                        Maximum number of concurrent async RPC tests (default: 5).


</pre>

### Change Log

<p>
 - Now async by default
 - Super improved errror handling
 - Faster with non blocking io
</p>


### Usage


<p>

This script downloads a list of RPCS and then times their exceution by calling `eth.get_block('latest, full_transactions=True`) and a few other methods to determine the RPC functions, and then sorts and outputs each RPC url ang it's exec time. Obviously a shorter tine is faster.  You can use the `--quick` flag to disable the more intensive testing if you'd like, although I do not recommend it.
  
</p>

<p>
NOTICE: make sure you set an infura API key env variable via dotenv or otherwise (`INFURA_API_KEY`) 
</p>


<pre>
anon@foffmybox:~/PycharmProjects/Ethersweep$ venv/bin/python3 rpc_lib.py 56 http
[('https://bsc-dataseed2.bnbchain.org', 0.2849881649017334),
 ('https://bsc-dataseed4.bnbchain.org', 0.16158127784729004),
 ('https://bsc-rpc.publicnode.com', 0.16069602966308594),
 ('https://bsc-dataseed3.bnbchain.org', 0.15935897827148438),
 ('https://bsc-dataseed4.ninicoin.io', 0.14779329299926758),
 ('https://bsc-dataseed4.defibit.io', 0.1476428508758545),
 ('https://bsc-dataseed3.ninicoin.io', 0.1469876766204834),
 ('https://bsc-dataseed1.bnbchain.org', 0.14656591415405273),
 ('https://bsc-dataseed2.defibit.io', 0.14315366744995117),
 ('https://bsc-dataseed1.defibit.io', 0.141876220703125),
 ('https://bsc-dataseed2.ninicoin.io', 0.14111661911010742),
 ('https://bsc-dataseed3.defibit.io', 0.14093875885009766),
 ('https://bsc-dataseed1.ninicoin.io', 0.14092755317687988)]

</pre>


### ToDo
  - Create a requirements.txt
  - Create async version
