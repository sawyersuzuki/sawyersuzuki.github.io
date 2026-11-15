"""Small HTTP helpers shared by the adapters: retries, byte ranges, S3 listing."""

from __future__ import annotations

import io
import re
import threading
import time

import requests
from requests.adapters import HTTPAdapter, Retry


class NotAvailable(Exception):
    """The requested run or field is not published (yet, or any more)."""


_local = threading.local()


def session() -> requests.Session:
    """One pooled session per thread."""
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        retry = Retry(total=6, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504))
        s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=32))
        _local.session = s
    return s


def _request(url: str, headers: dict | None, timeout: int) -> bytes:
    """GET with a second layer of retries for dropped connections and throttling."""
    last: Exception | None = None
    for attempt in range(4):
        try:
            resp = session().get(url, headers=headers, timeout=timeout)
            if resp.status_code in (403, 404):
                raise NotAvailable(url)
            resp.raise_for_status()
            return resp.content
        except NotAvailable:
            raise
        except requests.RequestException as e:  # includes broken reads and exhausted retries
            last = e
            time.sleep(2.0 * (attempt + 1))
    raise last  # type: ignore[misc]


def get(url: str, timeout: int = 120) -> bytes:
    return _request(url, None, timeout)


def get_range(url: str, offset: int, length: int | None, timeout: int = 120) -> bytes:
    """Bytes [offset, offset+length) of a remote file; to end of file if length is None."""
    end = "" if length is None else str(offset + length - 1)
    return _request(url, {"Range": f"bytes={offset}-{end}"}, timeout)


def exists(url: str) -> bool:
    resp = session().head(url, timeout=60)
    return resp.status_code == 200


def s3_list(bucket_url: str, prefix: str, delimiter: str = "/") -> tuple[list[str], list[str]]:
    """(common prefixes, keys) directly under ``prefix`` in a public S3 bucket."""
    prefixes: list[str] = []
    keys: list[str] = []
    token = None
    while True:
        params = {"list-type": "2", "prefix": prefix, "delimiter": delimiter}
        if token:
            params["continuation-token"] = token
        text = session().get(bucket_url, params=params, timeout=60).text
        prefixes += re.findall(r"<CommonPrefixes><Prefix>([^<]+)</Prefix>", text)
        keys += re.findall(r"<Key>([^<]+)</Key>", text)
        more = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        if not more:
            return prefixes, keys
        token = more.group(1)


class RangeFile(io.RawIOBase):
    """Read-only, seekable view of a remote file, fetched in cached blocks.

    Lets h5py read the small metadata of a multi-gigabyte NetCDF file without
    downloading it.
    """

    def __init__(self, url: str, block: int = 1 << 20):
        self.url, self.block, self.pos = url, block, 0
        head = session().head(url, timeout=60)
        if head.status_code in (403, 404):
            raise NotAvailable(url)
        head.raise_for_status()
        self.size = int(head.headers["Content-Length"])
        self._blocks: dict[int, bytes] = {}

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence]
        self.pos = base + offset
        return self.pos

    def _block(self, i: int) -> bytes:
        if i not in self._blocks:
            self._blocks[i] = get_range(self.url, i * self.block, min(self.block, self.size - i * self.block))
        return self._blocks[i]

    def readinto(self, buffer) -> int:
        n = min(len(buffer), self.size - self.pos)
        if n <= 0:
            return 0
        out = bytearray()
        pos = self.pos
        while len(out) < n:
            i, off = divmod(pos, self.block)
            piece = self._block(i)[off : off + n - len(out)]
            out += piece
            pos += len(piece)
        buffer[:n] = out
        self.pos = pos
        return n
