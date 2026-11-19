"""Extract the text of chosen PDF pages, in a separate, limited process (P2-7).

Run only by `munisense.ingestion.citation_check`, as `python -I pdf_text.py <request-json>`,
inside resource limits the parent sets (address space, CPU time, wall time). This file
imports only the standard library and pypdf, so the child loads nothing else.

Output, on standard output, one JSON object:
`{"pages": {"<n>": "<text>"}}` or `{"error": "<what went wrong>"}`.
"""

import json
import sys

# pypdf's own limits, set explicitly so an upgrade cannot loosen them. They are pypdf
# 6.21's defaults; the committed documents need far less (P2-7 pull request).
PYPDF_LIMITS = {
    "maximum_declared_stream_length": 75_000_000,
    "zlib_maximum_output_length": 75_000_000,
    "lzw_maximum_output_length": 75_000_000,
    "run_length_maximum_output_length": 75_000_000,
    "array_based_stream_maximum_output_length": 75_000_000,
    "image_maximum_buffer_size": 75_000_000,
    "stream_decoding_work_maximum_length": 300_000_000,
    "stream_parsing_work_maximum_count": 2_000_000,
    "page_tree_maximum_entries": 100_000,
    "xform_maximum_invocations_per_extraction": 5_000,
}


def extract(path: str, pages: list[int], maximum_pages: int) -> dict[str, object]:
    import logging  # imported here, after the parent's limits apply

    from pypdf import Configuration, PdfReader, overwrite_configuration

    logging.disable(logging.WARNING)  # pypdf's font warnings would go to standard error
    overwrite_configuration(Configuration().with_overwrites(**PYPDF_LIMITS))
    reader = PdfReader(path, strict=False)
    count = len(reader.pages)
    if count > maximum_pages:
        return {"error": f"the document has {count} pages, more than the limit of {maximum_pages}"}
    texts: dict[str, str] = {}
    for page in pages:
        if not 1 <= page <= count:
            return {"error": f"page {page} does not exist (the document has {count} pages)"}
        texts[str(page)] = reader.pages[page - 1].extract_text() or ""
    return {"pages": texts}


def main(argv: list[str]) -> int:
    request = json.loads(argv[1])
    try:
        result = extract(request["path"], request["pages"], request["maximum_pages"])
    except Exception as error:  # any failure is reported, never raised
        result = {"error": f"{type(error).__name__}: {error}"[:300]}
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":  # pragma: no cover  # runs only in the child process
    raise SystemExit(main(sys.argv))
