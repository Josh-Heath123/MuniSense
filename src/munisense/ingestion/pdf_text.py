"""Extract the text of chosen PDF pages, in a separate, limited process (P2-7).

Run only by `munisense.ingestion.citation_check`, as `python -I pdf_text.py <request-json>`,
with the PDF's bytes on standard input, an empty environment and `/` as working directory.
The child opens no file by name. Its first act is to set its own resource limits (soft
equal to hard, so they cannot be raised): address space, CPU time, no file writes, no core
dumps and few file descriptors. Only then does it import pypdf, with every pypdf limit
pinned.

Output, on standard output, one JSON object:
`{"page_count": <n>, "pages": {"<n>": "<text>"}}` or `{"error": "<what went wrong>"}`.

The child is resource-limited, not sandboxed: a parser bug that ran code could still read
the user's files and use the network (security register).
"""

import io
import json
import sys
from typing import Any, BinaryIO

# Every limit in pypdf 6.21's `Configuration`, pinned to pypdf's defaults so an upgrade
# cannot loosen them; a test fails if pypdf adds a field this does not name. The committed
# documents need far less (measured in the P2-7 pull request).
PYPDF_LIMITS: dict[str, Any] = {
    "maximum_declared_stream_length": 75_000_000,
    "array_based_stream_maximum_output_length": 75_000_000,
    "array_maximum_element_count": 100_000,
    "dictionary_maximum_element_count": 100_000,
    "jbig2_maximum_output_length": 75_000_000,
    "lzw_maximum_output_length": 75_000_000,
    "run_length_maximum_output_length": 75_000_000,
    "zlib_maximum_output_length": 75_000_000,
    "zlib_maximum_recovery_input_length": 5_000_000,
    "brotli_maximum_output_length": 75_000_000,
    "flate_maximum_columns": 250_000,
    "flate_maximum_row_length": 4_000_000,
    "image_maximum_buffer_size": 75_000_000,
    "stream_filters_maximum_length": 16,
    "stream_decoding_work_maximum_length": 300_000_000,
    "stream_parsing_work_maximum_count": 2_000_000,
    "xmp_maximum_input_length": 5_000_000,
    "xmp_maximum_element_count": 100_000,
    "outline_maximum_entries": 100_000,
    "outline_maximum_depth": 100,
    "page_tree_maximum_entries": 100_000,
    "page_tree_maximum_depth": 100,
    "page_tree_maximum_page_entries": 2_000_000,
    "form_fields_maximum_entries": 100_000,
    "form_fields_maximum_depth": 100,
    "xform_maximum_invocations_per_extraction": 5_000,
    "jbig2dec_binary": None,  # never run an external decoder found on PATH
}
NOT_LIMITS = frozenset({"page_merge_box", "disable_legacy_handling"})
"""`Configuration` fields that are behaviour switches, not limits; left at pypdf's default."""


def set_limits(address_space: int, cpu_seconds: int) -> None:
    """Hard limits for this process. Called before pypdf is imported."""
    import resource  # the child imports as little as possible

    for name, value in (
        ("RLIMIT_AS", address_space),
        ("RLIMIT_CPU", cpu_seconds),
        ("RLIMIT_FSIZE", 0),
        ("RLIMIT_CORE", 0),
        ("RLIMIT_NOFILE", 64),
    ):
        resource.setrlimit(getattr(resource, name), (value, value))


def extract(data: bytes, pages: list[int], maximum_pages: int) -> dict[str, object]:
    """The text of `pages` (1-based) of the PDF in `data`, with pypdf's limits applied."""
    from pypdf import Configuration, PdfReader, apply_configuration

    with apply_configuration(Configuration().with_overwrites(**PYPDF_LIMITS)):
        reader = PdfReader(io.BytesIO(data), strict=False)
        count = len(reader.pages)
        if count > maximum_pages:
            return {
                "error": f"the document has {count} pages, more than the limit of {maximum_pages}"
            }
        texts: dict[str, str] = {}
        for page in pages:
            if not 1 <= page <= count:
                return {"error": f"page {page} does not exist (the document has {count} pages)"}
            texts[str(page)] = reader.pages[page - 1].extract_text() or ""
    return {"page_count": count, "pages": texts}


def main(argv: list[str], stdin: BinaryIO) -> int:
    request = json.loads(argv[1])
    set_limits(request["address_space"], request["cpu_seconds"])
    import logging

    logging.disable(logging.WARNING)  # pypdf's font warnings would go to standard error
    try:
        data = stdin.read(request["file_bytes"] + 1)
        result = extract(data, request["pages"], request["maximum_pages"])
    except Exception as error:  # any failure is reported, never raised
        result = {"error": type(error).__name__}
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":  # pragma: no cover  # runs only in the child process
    raise SystemExit(main(sys.argv, sys.stdin.buffer))
