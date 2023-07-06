DomainMetadataBytes = list[tuple[bytes, bytes]]  # this is from the clvm code directly
DomainMetadataRaw = list[tuple[str, str]]


def metadata_bytes_to_raw(metadata: DomainMetadataBytes) -> DomainMetadataRaw:
    return [(key.decode("utf-8"), value.decode("utf-8")) for key, value in metadata]
