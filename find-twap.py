
import os
import asyncio
import json
from dotenv import load_dotenv

from web3 import Web3
from web3.middleware import geth_poa_middleware


from services.external_api.client import RetryConfig
from starkware.starknet.services.api.gateway.transaction import Deploy, InvokeFunction
from starkware.starknet.compiler.compile import compile_starknet_files, get_selector_from_name
from starkware.cairo.lang.vm.crypto import pedersen_hash
from utils.types import Data
from utils.block_header import build_block_header
from utils.Signer import Signer
from utils.create_account import create_account
from starknet_py.net.gateway_client import GatewayClient
from starknet_py.net.models.chains import StarknetChainId
from starknet_py.net import AccountClient, KeyPair
from starknet_py.net.signer.stark_curve_signer import KeyPair, StarkCurveSigner
from starknet_py.contract import Contract

DEFAULT_MAX_FEE = int(1e18)

testnet = "testnet"
chain_id = StarknetChainId.TESTNET
load_dotenv()

eth_provider_url = f"https://eth-goerli.alchemyapi.io/v2/{os.getenv('alchemy_api_key')}"
provider = Web3.HTTPProvider(eth_provider_url)
web3 = Web3(provider)
# web3.middleware_onion.inject(geth_poa_middleware, layer=0)

def get_gateway_client() -> GatewayClient:
    # Limit the number of retries.
    retry_config = RetryConfig(n_retries=1)
    return GatewayClient(net=testnet)



starknet_core_addr = '0xde29d060D45901Fb19ED6C6e959EB22d8626708e'


async def register_computation_twap(client, twap_contract_address, start_block, end_block,parameter,  callback_address):
    twapcontract = Contract(
        twap_contract_address,
        json.load(open('TWAP.json')),
        client,
    )
    tx_receipt = await (await twapcontract.functions["register_computation"].invoke(start_block, end_block, parameter, int(callback_address, 16),max_fee=int(1e16))).wait_for_acceptance()
    # twap_register_computation_tx = InvokeFunction(
    #         contract_address=int(twap_contract_address, 16),
    #         entry_point_selector=get_selector_from_name('register_computation'),
    #         calldata=[start_block, end_block, parameter, int(callback_address, 16)],
    #         signature=[],
    #         max_fee=0,
    #         version=0)
    # tx_receipt = await client.add_transaction(twap_register_computation_tx)
    
    print(f'Register computation receipt {tx_receipt}')

async def compute_twap(client, twap_contract_address, _calldata):

    # If the ABI is known, create the contract directly (this is the preferred way).
    twapcontract = Contract(
        twap_contract_address,
        json.load(open('TWAP.json')),
        client,
    )

    tx_receipt = await (await twapcontract.functions["compute"].invoke(_calldata,max_fee=int(1e16))).wait_for_acceptance()
    # twap_compute_tx = InvokeFunction(
    #         contract_address=int(twap_contract_address, 16),
    #         entry_point_selector=get_selector_from_name('compute'),
    #         calldata=_calldata,
    #         signature=[],
    #         max_fee=0,
    #         version=0)
    # tx_receipt = await client.add_transaction(twap_compute_tx)

    print(f'compute TWAP receipt {tx_receipt}')


## Remember end_block < start_block, so we are working in backward direction from beginning start block
start_block_number = 7712260 # The block you send to L1 Messaging Contract, should be --> start_block + 1
end_block_number = 7712259
parameter_num = 15 # basefee --> 15, difficulty --> 7, gas_used --> 10


twap_contract_address = os.getenv("STARKNET_TWAP_ADDR")
twap_callback_address = os.getenv("STARKNET_TWAP_CALLBACK_ADDR")

secrets = json.load(open('secrets.json'))
gateway_client = get_gateway_client()
l2_priv_key = secrets['l2_priv_key']
l2_account_address = secrets['l2_account_address']

# There is another way of creating key_pair
key_pair = KeyPair.from_private_key(key=int(l2_priv_key))

# Instead of providing key_pair it is possible to specify a signer
signer = StarkCurveSigner(int(l2_account_address), key_pair, StarknetChainId.TESTNET)

account_client = AccountClient(client=gateway_client, address=int(l2_account_address), signer=signer)


# Register Computation Starts Here
loop = asyncio.get_event_loop()
loop.run_until_complete(register_computation_twap(account_client, twap_contract_address, start_block_number, end_block_number,parameter_num,  twap_callback_address))
loop.close()
# Register Computation Ends Here

# Calculate Pedersen Hash
tmp_1 = pedersen_hash(start_block_number, end_block_number)
tmp_2 = pedersen_hash(tmp_1, int(twap_callback_address,16))
computation_id = pedersen_hash(tmp_2, parameter_num)
print("Computation ID: ", computation_id)
# Pedersen Hash Ends Here

# Preparing calldata starts here
headers_lengths_bytes = []
headers_lengths_words = []
concat_headers = []
for block_num in range(start_block_number, end_block_number - 1, -1):
    block = dict(web3.eth.get_block(block_num))
    block_header = build_block_header(block)
    print(block_header)
    block_rlp = Data.from_bytes(block_header.raw_rlp()).to_ints()
    print("Block Number: ", block_num , " ,blockhash: ", block_header.hash().hex())
    headers_lengths_bytes.append(block_rlp.length)
    headers_lengths_words.append(len(block_rlp.values))
    concat_headers.extend(block_rlp.values)

calldata = [
    computation_id,
    len(headers_lengths_bytes),
    *headers_lengths_bytes,
    len(headers_lengths_words),
    *headers_lengths_words,
    len(concat_headers),
    *concat_headers
]
print(calldata)
# Preparing calldata ends here
loop = asyncio.new_event_loop()
loop.run_until_complete(compute_twap(account_client, twap_contract_address, calldata))
loop.close()