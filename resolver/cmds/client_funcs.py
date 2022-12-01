from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from blspy import G2Element, PrivateKey
from chia.consensus.block_record import BlockRecord
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.derive_keys import master_sk_to_farmer_sk
from chia.wallet.transaction_record import TransactionRecord

from resolver.drivers.domain_info import DomainInfo
from resolver.drivers.puzzle_class import validate_initial_spend
from resolver.drivers.puzzle_drivers import DomainInnerPuzzle, DomainOuterPuzzle, DomainPuzzle
from resolver.puzzles.domain_constants import MAX_REGISTRATION_GAP, REGISTRATION_LENGTH


class NodeClient:
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        root_path: Path = DEFAULT_ROOT_PATH,
        rpc_port: Optional[uint16] = None,
    ) -> None:
        if config is None:
            config = load_config(root_path, "config.yaml")
        if rpc_port is None:
            rpc_port = uint16(config["full_node"]["rpc_port"])
        self.config = config
        self.rpc_port = rpc_port
        self.root_path = root_path
        self.client: Optional[FullNodeRpcClient] = None
        overrides = config["network_overrides"]["constants"][config["selected_network"]]
        self.constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
        self.constants_tuple = (self.constants.AGG_SIG_ME_ADDITIONAL_DATA, self.constants.MAX_BLOCK_COST_CLVM)

    async def start(self) -> None:
        self_hostname = self.config["self_hostname"]
        self.client = await FullNodeRpcClient.create(self_hostname, self.rpc_port, self.root_path, self.config)

    async def stop(self) -> None:
        if self.client is not None:
            self.client.close()
            await self.client.await_closed()
            self.client = None
        return None

    async def get_peak_and_last_tx(self) -> Tuple[BlockRecord, BlockRecord]:
        """
        This function returns the peak block and the last transaction block.
        If the peak block is a transaction block, it will return the peak block as both.
        :return: The peak block and the last transaction block.
        """
        if self.client is None:
            raise ValueError("Not Connected to a Node.")
        blockchain_state = await self.client.get_blockchain_state()
        if not blockchain_state["sync"]["synced"]:
            raise ValueError("Node is not synced.")
        peak: BlockRecord = blockchain_state["peak"]
        if peak is not None:
            if peak.is_transaction_block:
                return peak, peak
            else:
                peak_hash = peak.header_hash
                curr = await self.client.get_block_record(peak_hash)
                while curr is not None and not curr.is_transaction_block:
                    curr = await self.client.get_block_record(curr.prev_hash)
                if curr is not None:
                    return peak, curr
        raise ValueError("No transaction blocks found.")

    async def discover_all_domains(
        self, domain_name: str, launcher_ids: Optional[List[bytes32]] = None
    ) -> List[DomainInfo]:
        """
        This function finds all domains that match the given domain name.
        & it returns a list of domain spends, with the most up-to-date renewal times.
        :param domain_name: The domain name you would like to resolve
        :param launcher_ids: (Optional) Only search these launcher IDs
        :return: List of unfiltered & unresolved DomainInfo Objects.
        """
        if self.client is None:
            raise ValueError("Not Connected to a Node.")
        blockchain_state = await self.client.get_blockchain_state()
        if not blockchain_state["sync"]["synced"]:
            raise ValueError("Node is not synced.")
        domain_ph = DomainPuzzle(domain_name).complete_puzzle_hash()
        # we get all coins for that ph.
        coin_records: List[CoinRecord] = [
            cr for cr in await self.client.get_coin_records_by_puzzle_hash(domain_ph) if cr.coin.amount == 1
        ]

        launcher_ids_heights_and_ts: Dict[bytes32, List[Tuple[uint32, uint64]]] = {}
        # {l_id: [(block_height, timestamp)]}
        # now we extract the launcher id's and renewal / creation heights from the coin spends.
        for cr in coin_records:
            cr_height: uint32 = cr.confirmed_block_index  # renewal / creation height.
            cr_timestamp: uint64 = cr.timestamp  # renewal / creation timestamp
            # now we get the spend that created each coin.
            p_spend: Optional[CoinSpend] = await self.client.get_puzzle_and_solution(
                cr.coin.parent_coin_info, cr_height
            )
            # we check if the fee ph matches & extract the launcher_id
            l_id = validate_initial_spend(p_spend)
            # filter out launcher_ids if applicable.
            if l_id is not None and (launcher_ids is None or l_id in launcher_ids):
                # we use a dictionary and a list because domains can be renewed.
                if l_id in launcher_ids_heights_and_ts:
                    launcher_ids_heights_and_ts[l_id].append((cr_height, cr_timestamp))
                else:
                    launcher_ids_heights_and_ts[l_id] = [(cr_height, cr_timestamp)]

        # now we get the children of the launcher coins, or the 1st domain singletons.
        launcher_children_list: List[CoinRecord] = await self.client.get_coin_records_by_parent_ids(
            list(launcher_ids_heights_and_ts.keys())  # launcher_ids
        )
        first_domain_spends: List[DomainInfo] = []
        for first_domain_cr in launcher_children_list:
            launcher_id_record = launcher_ids_heights_and_ts[first_domain_cr.coin.parent_coin_info]  # height, timestamp
            expected_height: uint32 = first_domain_cr.confirmed_block_index  # ephemeral so should match
            creation_timestamp: uint64 = first_domain_cr.timestamp
            renewal_timestamps: List[uint64] = [v[1] for v in launcher_id_record]  # list of timestamps
            latest_renewal_timestamp: uint64 = max(renewal_timestamps)

            # validate that height and timestamp match expected values and were previously identified.
            if (expected_height, creation_timestamp) not in launcher_id_record:
                continue
            # now we check for gaps in the height (expired), and if there are any, we skip this domain record.
            if not self._validate_renewal_times(renewal_timestamps):
                continue
            first_domain_spend: Optional[CoinSpend] = await self.client.get_puzzle_and_solution(
                first_domain_cr.name, expected_height
            )
            # we now validate height yet again, by checking None because it should be spent in that same block.
            if first_domain_spend is not None:
                # now we simply parse and save the domain info.
                try:
                    d_info: DomainInfo = DomainInfo.from_coin_spend(
                        spend=first_domain_spend,
                        spend_height=expected_height,
                        creation_height=expected_height,
                        creation_timestamp=creation_timestamp,
                        renewal_timestamp=latest_renewal_timestamp,
                        const_tuple=self.constants_tuple,
                    )
                    first_domain_spends.append(d_info)
                except ValueError:  # if it is not a real spend we just ignore it.
                    pass
        return first_domain_spends

    @staticmethod
    def _validate_renewal_times(renewal_timestamps: List[uint64]) -> bool:
        # sort timestamps in any order.
        renewal_timestamps.sort()
        # now we check if the timestamps are not too far apart.
        cur_timestamp: uint64 = renewal_timestamps[0]
        for timestamp in renewal_timestamps:
            if timestamp - cur_timestamp > MAX_REGISTRATION_GAP:
                return False
        return True

    async def resolve_domain(self, domain_record: DomainInfo) -> DomainInfo:
        """
        This function takes a DomainInfo object and resolves it to the most up-to-date DomainInfo object.
        :param domain_record: an unresolved domain records.
        :return: a single resolved record.
        """
        if self.client is None:
            raise ValueError("Not Connected to a Node.")
        blockchain_state = await self.client.get_blockchain_state()
        if not blockchain_state["sync"]["synced"]:
            raise ValueError("Node is not synced.")
        # now we start by getting the most recent Coin Record.
        curr_record: CoinRecord = (await self.client.get_coin_records_by_parent_ids([domain_record.name]))[0]
        while curr_record.spent:
            curr_record = (await self.client.get_coin_records_by_parent_ids([curr_record.name]))[0]
        # now we get the spend bundle that created that coin.
        spend_height = curr_record.confirmed_block_index
        final_spend: Optional[CoinSpend] = await self.client.get_puzzle_and_solution(
            curr_record.coin.parent_coin_info, spend_height
        )
        assert final_spend is not None  # this should never happen.
        return DomainInfo.from_coin_spend(
            spend=final_spend,
            spend_height=spend_height,
            creation_height=domain_record.creation_height,
            creation_timestamp=domain_record.creation_timestamp,
            renewal_timestamp=domain_record.renewal_timestamp,
            const_tuple=self.constants_tuple,
        )

    async def filter_domains(
        self, domain_records: List[DomainInfo], include_grace_period: bool = False
    ) -> Optional[DomainInfo]:
        """
        This function filters out expired and or conflicting domains, and returns the final, unresolved domain.
        :param domain_records: List of unresolved / unfiltered domain records of the same name.
        :param include_grace_period: should we include domains that are in their grace period.
        :return: The correct, domain record, if there is one.
        """
        if self.client is None:
            raise ValueError("Not Connected to a Node.")
        current_block, last_tx_block = await self.get_peak_and_last_tx()
        latest_timestamp: Optional[uint64] = last_tx_block.timestamp
        assert latest_timestamp is not None  # tx always has a timestamp
        # we now filter out expired domains
        for domain_record in domain_records:
            if include_grace_period and domain_record.in_grace_period(latest_timestamp):
                continue
            if domain_record.is_expired(latest_timestamp):
                domain_records.remove(domain_record)
        domains_to_resolve: Optional[DomainInfo] = None
        if len(domain_records) == 1:
            domains_to_resolve = domain_records[0]
        elif len(domain_records) > 1:
            domain_records.sort(key=lambda x: x.creation_height)  # sort from least to greatest creation heights.
            # select the oldest block.
            lowest_block_height: uint32 = domain_records[0].creation_height
            # now we check if there are any other domains from that block
            possible_records: List[DomainInfo] = []
            for domain_record in domain_records:
                if domain_record.creation_height == lowest_block_height:
                    possible_records.append(domain_record)
            if len(possible_records) > 1:
                # We need an easy way to resolve conflicts, so
                # we sort from least to greatest by launcher_id, and select the first one.
                possible_records.sort(key=lambda x: x.launcher_id)
            domains_to_resolve = possible_records[0]
        # now we simply return the remaining record
        return domains_to_resolve

    async def spend_old_markers(self, domain_name: str) -> Optional[SpendBundle]:
        """
        This function spends all the old markers that are associated with a domain name.
        This does not really ever need to be used but it's cool to have.
        :param domain_name: Any Domain Name
        :return: SpendBundle if any markers were spent, None otherwise.
        """
        if self.client is None:
            raise ValueError("Not Connected to a Node.")
        current_block, last_tx_block = await self.get_peak_and_last_tx()
        latest_timestamp: Optional[uint64] = last_tx_block.timestamp
        assert latest_timestamp is not None  # tx always has a timestamp
        domain_class = DomainPuzzle(domain_name)
        domain_ph = domain_class.complete_puzzle_hash()
        # we get all coins for that ph & convert those coins to coin spends.
        coin_spends: List[CoinSpend] = [
            domain_class.to_coin_spend(cr.coin)
            for cr in await self.client.get_coin_records_by_puzzle_hash(domain_ph, False)
            if cr.coin.amount == 1 and cr.timestamp + REGISTRATION_LENGTH < latest_timestamp
        ]
        if len(coin_spends) == 0:
            return None
        # now we create a spend bundle, push it to our node and return it.
        sb = SpendBundle(coin_spends, G2Element())
        await self.client.push_tx(sb)
        return sb


class WalletClient:
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        root_path: Path = DEFAULT_ROOT_PATH,
        rpc_port: Optional[uint16] = None,
    ) -> None:
        if config is None:
            config = load_config(root_path, "config.yaml")
        if rpc_port is None:
            rpc_port = uint16(config["wallet"]["rpc_port"])
        self.config = config
        self.rpc_port = rpc_port
        self.root_path = root_path
        self.client: Optional[WalletRpcClient] = None
        overrides = config["network_overrides"]["constants"][config["selected_network"]]
        self.constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
        self.master_private_key: Optional[PrivateKey] = None
        self.farmer_private_key: Optional[PrivateKey] = None  # we use this for now
        self.fingerprint: Optional[int] = None
        self.node_client: Optional[NodeClient] = None

    async def start(self, fingerprint: int, node_client: NodeClient) -> None:
        self.node_client = node_client
        self_hostname = self.config["self_hostname"]
        self.client = await WalletRpcClient.create(self_hostname, self.rpc_port, self.root_path, self.config)
        log_in_response = await self.client.log_in(fingerprint)
        if log_in_response["success"] is False:
            print(f"Login failed: {log_in_response}")
            raise ValueError("Login failed")
        self.fingerprint = fingerprint
        self.master_private_key = PrivateKey.from_bytes(
            hexstr_to_bytes((await self.client.get_private_key(fingerprint))["sk"])
        )
        self.farmer_private_key = master_sk_to_farmer_sk(self.master_private_key)

    async def stop(self) -> None:
        if self.client is not None:
            self.client.close()
            await self.client.await_closed()
            self.client = None

    async def create_domain(
        self,
        wallet_id: int,
        domain_name: str,
        metadata: List[Tuple[str, str]],
        fee: uint64,
        skip_existing_check: bool = False,
    ) -> Optional[Tuple[TransactionRecord, SpendBundle]]:
        """
        This function creates a domain name and returns the spend bundle that would create it.
        If a non expired domain name already exists, it will return None, unless skip_existing_check is True.
        :param fee: transaction fee
        :param wallet_id: the id of the wallet
        :param skip_existing_check: if this is true, then we don't check if a domain already exists.
        :param domain_name: the domain_name to create
        :param metadata: a list of tuples of metadata to add to the domain name.
        :return: SpendBundle if successful, None otherwise.
        """
        if self.client is None:
            raise ValueError("Not Connected to a Wallet.")
        if self.node_client is None:
            raise ValueError("Not Connected to a Node.")
        if not skip_existing_check:
            # we first check if the domain name is already taken
            all_d_records = await self.node_client.discover_all_domains(domain_name)
            final_record = await self.node_client.filter_domains(all_d_records)
            if final_record is not None:  # Domain already exists
                return None
        # now that we have checked, we can create the inner domain puzzle.
        assert self.farmer_private_key is not None
        pub_key = self.farmer_private_key.get_g1()
        inner_class = DomainInnerPuzzle(domain_name, pub_key, metadata)
        # now we find a coin to use.
        removals: List[Coin] = await self.client.select_coins(
            amount=fee + 10000000002, wallet_id=wallet_id, min_coin_amount=uint64(fee + 10000000002)
        )
        if len(removals) > 1:
            raise ValueError("Too many coins selected, please condense the coins in your wallet.")
        assert removals[0].amount >= fee + 10000000002
        # now we get the args to create a spend bundle.
        (
            coin_assertions,
            puzzle_assertions,
            primaries,
            spend_bundle,
        ) = await DomainOuterPuzzle.create_singleton_from_inner(
            self.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.constants.MAX_BLOCK_COST_CLVM,
            self.farmer_private_key,
            inner_class,
            removals[0],
        )
        # now we create a transaction.
        tx: TransactionRecord = await self.client.create_signed_transaction(
            additions=primaries,
            coins=removals,
            fee=fee,
            coin_announcements=coin_assertions,
            puzzle_announcements=puzzle_assertions,
        )
        assert tx.spend_bundle is not None  # should never be none.
        # now we aggregate the spend bundles, and push the transaction.
        final_sb = SpendBundle.aggregate([spend_bundle, tx.spend_bundle])
        await self.client.push_tx(final_sb)
        return tx, final_sb

    async def renew_domain(
        self,
        wallet_id: int,
        domain_name: str,
        fee: uint64,
        new_metadata: Optional[List[Tuple[str, str]]] = None,
        launcher_id: Optional[bytes32] = None,
    ) -> Optional[Tuple[TransactionRecord, SpendBundle]]:
        """
        This function creates a domain name and returns the spend bundle that would create it.
        If a non expired domain name already exists, it will return None, unless skip_existing_check is True.
        :param launcher_id: the specific launcher_id to use.
        :param fee: transaction fee
        :param wallet_id: the id of the wallet
        :param domain_name: the domain_name to create
        :param new_metadata: a list of tuples of metadata to add to the domain name.
        :return: SpendBundle if successful, None otherwise.
        """
        if self.client is None:
            raise ValueError("Not Connected to a Wallet.")
        if self.node_client is None:
            raise ValueError("Not Connected to a Node.")
        # we first find the domain.
        if launcher_id is not None:
            l_id_list = [launcher_id]
        else:
            l_id_list = None
        all_d_records = await self.node_client.discover_all_domains(domain_name, l_id_list)
        # override if launcher id is expired.
        if launcher_id is None:
            cur_record: DomainInfo = await self.node_client.filter_domains(all_d_records)
        else:
            cur_record = all_d_records[0]
        if cur_record is None:  # Domain already exists
            return None
        # now that we have the domain, we resolve it & get the inner puzzle.
        cur_record = await self.node_client.resolve_domain(cur_record)
        assert self.farmer_private_key is not None
        private_key = self.farmer_private_key
        outer_class: DomainOuterPuzzle = cur_record.domain_class
        latest_coin: Coin = cur_record.full_spend.additions()[0]  # only 1 coin is ever created.
        # now we find a coin to use.
        removals: List[Coin] = await self.client.select_coins(
            fee + 10000000001, wallet_id, min_coin_amount=uint64(fee + 10000000001)
        )
        if len(removals) > 1:
            raise ValueError("Too many coins selected, please condense the coins in your wallet.")
        assert removals[0].amount >= fee + 10000000001
        # now we get the args to create a spend bundle.
        (puzzle_assertions, primaries, spend_bundle) = await outer_class.renew_domain(
            private_key, latest_coin, removals[0], new_metadata
        )
        # now we create a transaction.
        tx: TransactionRecord = await self.client.create_signed_transaction(
            additions=primaries,
            coins=removals,
            fee=fee,
            puzzle_announcements=puzzle_assertions,
        )
        assert tx.spend_bundle is not None  # should never be none.
        # now we aggregate the spend bundles, and push the transaction.
        final_sb = SpendBundle.aggregate([spend_bundle, tx.spend_bundle])
        await self.client.push_tx(final_sb)
        return tx, final_sb
