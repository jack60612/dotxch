from dataclasses import dataclass, field
from typing import NewType, Optional, Union

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash

from resolver.puzzles.domain_constants import METADATA_FORMAT_VERSION

DomainMetadataRaw = NewType(
    "DomainMetadataRaw", list[tuple[str, bytes]]
)  # this is after we convert the binary keys to strings
DomainMetadataDict = NewType("DomainMetadataDict", dict[str, Union[str, dict[str, str]]])


def decode_metadata_keys(metadata: list[tuple[bytes, bytes]]) -> DomainMetadataRaw:
    """
    Convert CLVM metadata keys from bytes to strings, to get DomainMetadataRaw
    :param metadata:
    :return:
    """
    return DomainMetadataRaw([(key.decode("utf-8"), value) for key, value in metadata])


@dataclass(frozen=True)
class DomainMetadata:
    metadata_version: str
    primary_address: bytes32
    chain_records: dict[str, bytes32] = field(default_factory=dict)
    dns_records: dict[str, str] = field(default_factory=dict)
    other_data: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: DomainMetadataRaw) -> "DomainMetadata":
        metadata_version: Optional[str] = None
        primary_address: Optional[bytes32] = None
        chain_records: dict[str, bytes32] = {}
        dns_records: dict[str, str] = {}
        other_data: dict[str, str] = {}
        for key, value in raw:
            if key == "metadata_version":
                metadata_version = value.decode("utf-8")
                if metadata_version != METADATA_FORMAT_VERSION:
                    raise ValueError(f"Unknown metadata version: {metadata_version}")
            elif key == "primary_address":
                primary_address = bytes32(value)
            elif key.startswith("chain."):
                chain_records[key[6:]] = bytes32(value)
            elif key.startswith("dns."):
                dns_records[key[4:]] = value.decode("utf-8")
            elif key.startswith("other."):
                other_data[key[6:]] = value.decode("utf-8")
            else:
                raise ValueError(f"Unknown metadata key: {key}")
        if metadata_version is None:
            raise ValueError("metadata_version is required")
        if primary_address is None:
            raise ValueError("primary_address is required")
        return cls(metadata_version, primary_address, chain_records, dns_records, other_data)

    def to_raw(self) -> DomainMetadataRaw:
        # we just leave the primary address as bytes32
        raw = [("metadata_version", METADATA_FORMAT_VERSION.encode("utf-8")), ("primary_address", self.primary_address)]
        for chain_key, chain_value in self.chain_records.items():
            raw.append((f"chain.{chain_key}", chain_value))
        # we also encode the string values as utf-8 bytes
        for dns_key, dns_value in self.dns_records.items():
            raw.append((f"dns.{dns_key}", dns_value.encode("utf-8")))
        for other_key, other_value in self.other_data.items():
            raw.append((f"other.{other_key}", other_value.encode("utf-8")))
        return DomainMetadataRaw(raw)

    @classmethod
    def from_dict(cls, meta_dict: DomainMetadataDict) -> "DomainMetadata":
        metadata_version = meta_dict["metadata_version"]
        assert type(metadata_version) == str
        if metadata_version != METADATA_FORMAT_VERSION:
            raise ValueError(f"Unknown metadata version: {metadata_version}")
        bech32_prim_addr = meta_dict["primary_address"]
        assert type(bech32_prim_addr) == str
        primary_address: bytes32 = decode_puzzle_hash(bech32_prim_addr)  # addr to ph
        # addr to ph
        assert type(meta_dict["chain_records"]) == dict
        chain_records: dict[str, bytes32] = {}
        for k, v in meta_dict["chain_records"].items():
            # validate prefix and key
            if "xch" not in k.lower() or "nft" not in k.lower() or "did" not in k.lower():
                raise ValueError(f"Invalid chain record key: {k}, the key must contain xch, nft or did")
            chain_records[k] = decode_puzzle_hash(v)

        dns_records = meta_dict.get("dns_records", {})
        assert type(dns_records) == dict
        other_data = meta_dict.get("other_data", {})
        assert type(other_data) == dict
        return cls(metadata_version, primary_address, chain_records, dns_records, other_data)

    def to_dict(self) -> DomainMetadataDict:
        chain_records: dict[str, str] = {}
        # encode with proper prefix
        for k, v in self.chain_records.items():
            if "xch" in k.lower():
                chain_records[k] = encode_puzzle_hash(v, "xch")
            elif "nft" in k.lower():
                chain_records[k] = encode_puzzle_hash(v, "nft")
            elif "did" in k.lower():
                chain_records[k] = encode_puzzle_hash(v, "did:chia:")
            else:
                raise ValueError(f"Invalid chain record key: {k}, the key must contain xch, nft or did")
        meta_dict: DomainMetadataDict = DomainMetadataDict(
            {
                "metadata_version": METADATA_FORMAT_VERSION,
                "primary_address": encode_puzzle_hash(self.primary_address, "xch"),
                "chain_records": chain_records,
                "dns_records": self.dns_records,
                "other_data": self.other_data,
            }
        )
        return meta_dict
