import dataclasses
from pathlib import Path
from typing import Any, Optional

from blspy import G1Element, G2Element, PrivateKey
from chia.consensus.block_record import BlockRecord
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.derive_keys import master_sk_to_farmer_sk
from chia.wallet.transaction_record import TransactionRecord

from resolver.drivers.domain_driver import DomainPuzzle
from resolver.drivers.domain_inner_driver import DomainInnerPuzzle
from resolver.drivers.domain_outer_driver import DomainOuterPuzzle
from resolver.drivers.puzzle_class import DomainMetadata, validate_initial_spend
from resolver.puzzles.domain_constants import REGISTRATION_LENGTH, TOTAL_FEE_AMOUNT, TOTAL_NEW_DOMAIN_AMOUNT
from resolver.types.domain_record import DomainRecord
from resolver.types.resolution_result import ResolutionResult
from resolver.types.resolution_status_code import ResolutionStatusCode


class NodeClient:
    def __init__(
        self,
        config: Optional[dict[str, Any]] = None,
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

    async def get_peak_and_last_tx(self) -> tuple[BlockRecord, BlockRecord]:
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
        self, domain_name: str, launcher_ids: Optional[list[bytes32]] = None
    ) -> list[ResolutionResult]:
        """
        This function finds all domains that match the given domain name.
        & it returns a list of domain spends, with the most up-to-date renewal times.
        :param domain_name: The domain name you would like to resolve
        :param launcher_ids: (Optional) Only search these launcher IDs
        :return: list of unfiltered & unresolved DomainRecord Objects.
        """
        if self.client is None:
            raise ValueError("Not Connected to a Node.")
        blockchain_state = await self.client.get_blockchain_state()
        if not blockchain_state["sync"]["synced"]:
            raise ValueError("Node is not synced.")
        _, last_tx_block = await self.get_peak_and_last_tx()
        latest_timestamp: Optional[uint64] = last_tx_block.timestamp
        assert latest_timestamp is not None  # tx always has a timestamp

        # Part 1: Get all Launcher IDs for the given domain name.
        # calculate the puzzle hash for the domain name.
        domain_ph = DomainPuzzle(domain_name).complete_puzzle_hash()
        # we get all coins for that ph.
        coin_records: list[CoinRecord] = [
            cr for cr in await self.client.get_coin_records_by_puzzle_hash(domain_ph) if cr.coin.amount == 1
        ]

        launcher_ids_heights_and_ts: dict[bytes32, list[tuple[uint32, uint64]]] = {}
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
        launcher_children_list: list[CoinRecord] = await self.client.get_coin_records_by_parent_ids(
            list(launcher_ids_heights_and_ts.keys())  # launcher_ids
        )
        # Part 2: Process the found launcher_ids.
        initial_resolution_results: list[ResolutionResult] = []
        for first_domain_cr in launcher_children_list:
            launcher_id_record = launcher_ids_heights_and_ts[first_domain_cr.coin.parent_coin_info]  # height, timestamp
            creation_height: uint32 = first_domain_cr.confirmed_block_index  # ephemeral so should match
            creation_timestamp: uint64 = first_domain_cr.timestamp
            renewal_timestamps: list[uint64] = [v[1] for v in launcher_id_record]  # list of timestamps
            renewal_heights: list[uint32] = [v[0] for v in launcher_id_record]  # list of heights
            registration_update_height: uint32 = max(renewal_heights)  # the height of the last renewal.

            # validate that height and timestamp match expected values and were previously identified.
            # if this fails, it means someone is trying to do something malicious.
            if (creation_height, creation_timestamp) not in launcher_id_record:
                continue
            # now we calculate the expiration timestamp.
            exp_timestamp: uint64 = self._calculate_expiration_timestamp(creation_timestamp, renewal_timestamps)
            # now we get the solution for the first singleton.
            first_singleton_spend: Optional[CoinSpend] = await self.client.get_puzzle_and_solution(
                first_domain_cr.name, creation_height
            )
            # we now validate height yet again, by checking None because it should be spent in that same block.
            if first_singleton_spend is not None:
                # now we simply parse and save the domain info.
                try:
                    d_rec: DomainRecord = DomainRecord.from_coin_spend(
                        creation_height=creation_height,
                        creation_timestamp=creation_timestamp,
                        registration_update_height=registration_update_height,
                        state_update_height=creation_height,
                        expiration_timestamp=exp_timestamp,
                        spend=first_singleton_spend,
                        const_tuple=self.constants_tuple,
                    )
                    r_result: ResolutionResult = ResolutionResult(
                        domain_name=domain_name,
                        status_code=d_rec.get_status_code(latest_timestamp),
                        domain_record=d_rec,
                    )
                    initial_resolution_results.append(r_result)
                except ValueError:  # if it is not a real spend we just ignore it.
                    pass
        return initial_resolution_results

    @staticmethod
    def _calculate_expiration_timestamp(creation_timestamp: uint64, renewal_timestamps: list[uint64]) -> uint64:
        # the creation timestamp is the starting point
        return uint64(creation_timestamp + ((len(renewal_timestamps) - 1) * REGISTRATION_LENGTH))

    async def get_latest_domain_state(self, res_result: ResolutionResult) -> ResolutionResult:
        """
        This function takes a ResolutionResult object and gets the latest version of the object from the blockchain.
        :param res_result: an unresolved resolution result.
        :return: a resolved resolution result.
        """
        if res_result.domain_record is None:
            return res_result
        if self.client is None:
            raise ValueError("Not Connected to a Node.")
        blockchain_state = await self.client.get_blockchain_state()
        if not blockchain_state["sync"]["synced"]:
            raise ValueError("Node is not synced.")
        domain_record = res_result.domain_record

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
        status_code = (
            ResolutionStatusCode.LATEST
            if res_result.status_code == ResolutionStatusCode.FOUND
            else res_result.status_code
        )
        final_domain_record = DomainRecord.from_coin_spend(
            creation_height=domain_record.creation_height,
            creation_timestamp=domain_record.creation_timestamp,
            registration_update_height=domain_record.registration_update_height,
            expiration_timestamp=domain_record.expiration_timestamp,
            state_update_height=spend_height,
            spend=final_spend,
            const_tuple=self.constants_tuple,
        )
        return ResolutionResult(res_result.domain_name, status_code, final_domain_record)

    async def filter_domains(
        self,
        res_results: list[ResolutionResult],
        allow_grace_period: bool = False,
        return_conflicting: bool = False,
    ) -> list[ResolutionResult]:
        """
        This function filters out expired and or conflicting domains, and returns the final, unresolved domain.
        :param res_results: list of unresolved / unfiltered resolution results of the same domain name.
        :param allow_grace_period: if we should accept domains that are in their grace period.
        :param return_conflicting: If we should return conflicting domains.
        :return: The correct, domain record, if there is one.
        """
        if self.client is None:
            raise ValueError("Not Connected to a Node.")
        current_block, last_tx_block = await self.get_peak_and_last_tx()
        latest_timestamp: Optional[uint64] = last_tx_block.timestamp
        assert latest_timestamp is not None  # tx always has a timestamp

        # we now filter out expired domains, while keeping grace period domains if specified.
        filtered_res_results: list[ResolutionResult] = [
            r_result
            for r_result in res_results
            if r_result.status_code == ResolutionStatusCode.FOUND
            or (allow_grace_period and r_result.status_code == ResolutionStatusCode.GRACE_PERIOD)
        ]
        domain_name = res_results[0].domain_name if len(res_results) > 0 else ""
        if len(filtered_res_results) == 0:
            res_to_resolve: ResolutionResult = ResolutionResult(domain_name, ResolutionStatusCode.EXPIRED, None)
        elif len(filtered_res_results) == 1:
            res_to_resolve = filtered_res_results[0]  # if there is only one, we can just return it.
        elif len(filtered_res_results) > 1:
            # sort from least to greatest creation heights.
            filtered_res_results.sort(key=lambda x: x.domain_record.creation_height)  # type: ignore
            # select the oldest block.
            lowest_block_height: uint32 = filtered_res_results[0].domain_record.creation_height  # type: ignore
            # now we check if there are any other domains from that block
            possible_records: list[ResolutionResult] = []
            for res_result in filtered_res_results:
                assert res_result.domain_record is not None
                if res_result.domain_record.creation_height == lowest_block_height:
                    possible_records.append(res_result)
                if res_result.domain_record.creation_height > lowest_block_height:
                    break
            if len(possible_records) > 1:
                # We need an easy deterministic way to resolve conflicts, so
                # we sort from least to greatest by launcher_id, and select the first one.
                possible_records.sort(key=lambda x: x.domain_record.launcher_id.hex())  # type: ignore
            res_to_resolve = possible_records[0]
        # now we know the one valid record.
        f_res_results: list[ResolutionResult] = [res_to_resolve]

        if return_conflicting:
            # add conflicting records.
            filtered_res_results.remove(res_to_resolve)
            f_res_results.extend(
                [dataclasses.replace(d, status_code=ResolutionStatusCode.CONFLICTING) for d in filtered_res_results]
            )
        return f_res_results

    async def spend_old_markers(self, domain_name: str) -> Optional[SpendBundle]:
        """
        This function spends all the old markers that are associated with a domain name.
        This does not really ever need to be used, but it's cool to have.
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
        coin_spends: list[CoinSpend] = [
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

    async def resolve_domain(
        self, domain_name: str, launcher_id: Optional[bytes32] = None, grace_period: bool = False
    ) -> ResolutionResult:
        """
        This function gets a ResolutionResult for a given domain name. (resolves it)
        :param domain_name: Any Domain Name
        :param launcher_id: If specified, we will only return the domain record for that launcher id.
        :param grace_period: If we should show domains that are in their grace period.
        :return Optional[DomainRecord]: Domain info if domain exists.
        """
        if self.client is None:
            raise ValueError("Not Connected to a Node.")
        # Find the Domain Records:
        launcher_ids = None
        if launcher_id is not None:
            launcher_ids = [launcher_id]
        all_res_results = await self.discover_all_domains(domain_name, launcher_ids)
        if len(all_res_results) == 0:  # no records found
            return ResolutionResult(domain_name, ResolutionStatusCode.NOT_FOUND, None)
        if not launcher_id:  # override if launcher id is expired.
            cur_record: ResolutionResult = (
                await self.filter_domains(all_res_results, allow_grace_period=grace_period)
            )[0]
        else:
            cur_record = all_res_results[0]
        # now that we have the domain, we resolve it (get latest info) & get the inner puzzle.
        return await self.get_latest_domain_state(cur_record)


class WalletClient:
    def __init__(
        self,
        node_client: NodeClient,
        config: Optional[dict[str, Any]] = None,
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
        self.node_client: NodeClient = node_client  # we always need a node.

        overrides = config["network_overrides"]["constants"][config["selected_network"]]
        self.constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)

        self.client: Optional[WalletRpcClient] = None
        self.master_private_key: Optional[PrivateKey] = None
        self.fingerprint: Optional[int] = None
        self.farmer_private_key: Optional[PrivateKey] = None  # we use this for now

    async def start(self, fingerprint: int) -> None:
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

    async def get_std_fee_tx(
        self,
        primaries: list[dict[str, Any]],
        fee: uint64,
        removals: Optional[list[Coin]] = None,
        coin_assertions: Optional[list[Announcement]] = None,
        puzzle_assertions: Optional[list[Announcement]] = None,
    ) -> TransactionRecord:
        assert self.client is not None
        tx: TransactionRecord = await self.client.create_signed_transaction(
            additions=primaries,
            coins=removals,  # type: ignore
            fee=fee,
            coin_announcements=coin_assertions,
            puzzle_announcements=puzzle_assertions,
        )
        return tx

    async def create_domain(
        self,
        wallet_id: int,
        domain_name: str,
        metadata: DomainMetadata,
        fee: uint64,
        skip_existing_check: bool = False,
        pub_key: Optional[G1Element] = None,
    ) -> Optional[tuple[TransactionRecord, SpendBundle]]:
        """
        This function creates a domain name and returns the spend bundle that would create it.
        If a non expired domain name already exists, it will return None, unless skip_existing_check is True.
        :param pub_key: A public key to use for the domain name. If None, we use the farmer public key.
        :param fee: transaction fee
        :param wallet_id: the id of the wallet
        :param skip_existing_check: if this is true, then we don't check if a domain already exists.
        :param domain_name: the domain_name to create
        :param metadata: a list of tuples of metadata to add to the domain name.
        :return: SpendBundle if successful, None otherwise.
        """
        # temp hack to get a key
        assert self.farmer_private_key is not None
        if pub_key is None:
            pub_key = self.farmer_private_key.get_g1()

        if self.client is None:
            raise ValueError("Not Connected to a Wallet.")

        if not skip_existing_check:
            # we first check if the domain name is already taken
            all_res_records = await self.node_client.discover_all_domains(domain_name)
            final_record = await self.node_client.filter_domains(all_res_records)
            if final_record[0].domain_record is not None:  # Domain already exists
                return None

        # now that we have checked, we can create the inner domain puzzle.
        inner_class = DomainInnerPuzzle(domain_name, pub_key, metadata)
        total_amount = fee + TOTAL_NEW_DOMAIN_AMOUNT
        # now we find a coin to use.
        removals: list[Coin] = await self.client.select_coins(
            amount=total_amount, wallet_id=wallet_id, min_coin_amount=uint64(total_amount)
        )
        if len(removals) > 1:
            raise ValueError("Too many coins selected, please condense the coins in your wallet.")
        assert removals[0].amount >= total_amount  # double check that the coin is big enough.
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
        tx: TransactionRecord = await self.get_std_fee_tx(
            primaries=primaries,
            fee=fee,
            removals=removals,
            coin_assertions=coin_assertions,
            puzzle_assertions=puzzle_assertions,
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
        new_metadata: Optional[DomainMetadata] = None,
        private_key: Optional[PrivateKey] = None,
        launcher_id: Optional[bytes32] = None,
    ) -> Optional[tuple[TransactionRecord, SpendBundle]]:
        """
        This function renews a domain name and returns the spend bundle that would create it.
        If a non expired domain name already exists, it will return None, unless a launcher_id is provided.
        :param private_key: (Optional) Default is farmer private key.
        :param wallet_id: the id of the wallet
        :param domain_name: the domain_name to renew
        :param fee: transaction fee
        :param launcher_id: the specific launcher_id to use.
        :param new_metadata: a list of tuples of metadata to add to the domain name.
        :return: SpendBundle if successful, None otherwise.
        """
        if private_key is None:
            # temporary hack to get a key, we can change later.
            assert self.farmer_private_key is not None
            private_key = self.farmer_private_key

        if self.client is None:
            raise ValueError("Not Connected to a Wallet.")

        cur_record = await self.node_client.resolve_domain(domain_name, launcher_id, True)
        if cur_record.domain_record is None:
            return None
        domain_rec: DomainRecord = cur_record.domain_record
        outer_class: DomainOuterPuzzle = domain_rec.domain_class
        latest_coin: Coin = compute_additions(domain_rec.full_spend)[0]  # only 1 coin is ever created.

        total_amount = fee + TOTAL_FEE_AMOUNT
        # now we find a coin to use.
        removals: list[Coin] = await self.client.select_coins(
            amount=total_amount, wallet_id=wallet_id, min_coin_amount=uint64(total_amount)
        )
        if len(removals) > 1:
            raise ValueError("Too many coins selected, please combine the coins in your wallet.")
        assert removals[0].amount >= total_amount

        # now we get the args to create a spend bundle.
        (puzzle_assertions, primaries, spend_bundle) = await outer_class.renew_domain(
            private_key, latest_coin, removals[0], new_metadata
        )
        # now we create a transaction.
        tx: TransactionRecord = await self.get_std_fee_tx(
            primaries=primaries,
            fee=fee,
            removals=removals,
            puzzle_assertions=puzzle_assertions,
        )
        assert tx.spend_bundle is not None  # should never be none.
        # now we aggregate the spend bundles, and push the transaction.
        final_sb = SpendBundle.aggregate([spend_bundle, tx.spend_bundle])
        await self.client.push_tx(final_sb)
        return tx, final_sb

    async def update_metadata(
        self,
        domain_name: str,
        fee: uint64,
        new_metadata: DomainMetadata,
        private_key: Optional[PrivateKey] = None,
        launcher_id: Optional[bytes32] = None,
    ) -> tuple[Optional[TransactionRecord], Optional[SpendBundle]]:
        """
        This function updates the metadata of  a domain name and returns the spend bundle that would create it.
        If a non expired domain name already exists, it will return None, unless a launcher_id is provided.
        :param private_key: (Optional) Default is farmer private key.
        :param domain_name: the domain_name to change the metadata of
        :param fee: transaction fee
        :param launcher_id: the specific launcher_id to use.
        :param new_metadata: a list of tuples of metadata to add to the domain name.
        :return: SpendBundle if successful, None otherwise.
        """
        if private_key is None:
            # temporary hack to get a key, we can change later.
            assert self.farmer_private_key is not None
            private_key = self.farmer_private_key

        if self.client is None:
            raise ValueError("Not Connected to a Wallet.")

        cur_record = await self.node_client.resolve_domain(domain_name, launcher_id, True)
        if cur_record.domain_record is None:
            return None, None
        domain_rec: DomainRecord = cur_record.domain_record
        outer_class: DomainOuterPuzzle = domain_rec.domain_class
        latest_coin: Coin = compute_additions(domain_rec.full_spend)[0]  # only 1 coin is ever created.

        # now we get the args to create a spend bundle.
        (puzzle_assertions, primaries, final_sb) = await outer_class.update_metadata(
            private_key,
            latest_coin,
            new_metadata,
        )

        tx: Optional[TransactionRecord] = None
        if fee > 0:
            # now we create a transaction.
            tx = await self.get_std_fee_tx(
                primaries=primaries,
                fee=fee,
                puzzle_assertions=puzzle_assertions,
            )
            assert tx.spend_bundle is not None  # should never be none.
            # now we aggregate the spend bundles, and push the transaction.
            final_sb = SpendBundle.aggregate([final_sb, tx.spend_bundle])
        await self.client.push_tx(final_sb)
        return tx, final_sb

    async def update_pubkey(
        self,
        domain_name: str,
        fee: uint64,
        new_metadata: DomainMetadata,
        new_pubkey: G1Element,
        private_key: Optional[PrivateKey] = None,
        launcher_id: Optional[bytes32] = None,
    ) -> tuple[Optional[TransactionRecord], Optional[SpendBundle]]:
        """
        This function updates the metadata of  a domain name and returns the spend bundle that would create it.
        If a non expired domain name already exists, it will return None, unless a launcher_id is provided.
        :param private_key: (Optional) Default is farmer private key.
        :param new_pubkey: New pubkey.
        :param domain_name: the domain_name to change the metadata of
        :param fee: transaction fee
        :param launcher_id: the specific launcher_id to use.
        :param new_metadata: a list of tuples of metadata to add to the domain name.
        :return: SpendBundle if successful, None otherwise.
        """
        if private_key is None:
            # temporary hack to get a key, we can change later.
            assert self.farmer_private_key is not None
            private_key = self.farmer_private_key

        if self.client is None:
            raise ValueError("Not Connected to a Wallet.")

        cur_record = await self.node_client.resolve_domain(domain_name, launcher_id, True)
        if cur_record.domain_record is None:
            return None, None
        domain_rec: DomainRecord = cur_record.domain_record
        outer_class: DomainOuterPuzzle = domain_rec.domain_class
        latest_coin: Coin = compute_additions(domain_rec.full_spend)[0]  # only 1 coin is ever created.

        # now we get the args to create a spend bundle.
        (puzzle_assertions, primaries, final_sb) = await outer_class.update_pubkey(
            private_key,
            latest_coin,
            new_metadata,
            new_pubkey,
        )

        tx: Optional[TransactionRecord] = None
        if fee > 0:
            # now we create a transaction.
            tx = await self.get_std_fee_tx(
                primaries=primaries,
                fee=fee,
                puzzle_assertions=puzzle_assertions,
            )
            assert tx.spend_bundle is not None  # should never be none.
            # now we aggregate the spend bundles, and push the transaction.
            final_sb = SpendBundle.aggregate([final_sb, tx.spend_bundle])
        await self.client.push_tx(final_sb)
        return tx, final_sb
