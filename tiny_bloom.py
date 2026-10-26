"""tiny-bloom - zero-dependency Bloom filter for Python.

A Bloom filter is a probabilistic set: it can tell you with certainty
that an element is NOT in the set, but may return a false positive.
tiny-bloom uses optimal bit sizing and a FNV-1a 64-bit hash for
membership tests.

Useful for:
  * URL deduplication in web crawlers.
  * Cache stampede prevention.
  * Probabilistic membership tests where false positives are tolerable.

Single file, no deps, MIT, public API in 1 class + 1 helper.
"""

from __future__ import annotations

import math
import struct
from typing import Iterable, Optional, Union


__version__ = "0.1.0"


# ---------- Hash (FNV-1a 64-bit, no deps) ----------

_FNV_OFFSET = 14695981039346656037
_FNV_PRIME = 1099511628211
_MASK64 = (1 << 64) - 1


def _fnv1a_64(data):
    h = _FNV_OFFSET
    for b in data:
        h ^= b
        h = (h * _FNV_PRIME) & _MASK64
    return h


def _double_hash(key, i, size):
    """Double-hashing trick from Kirsch & Mitzenmacher (2006).

    h_i = (h1 + i * h2) mod m. Lets us use one FNV-1a call (h1) and
    derive h2 via a splitmix64 finalizer.
    """
    if isinstance(key, str):
        key = key.encode("utf-8")
    h1 = _fnv1a_64(key)
    h2 = h1 ^ ((h1 >> 33) & _MASK64)
    h2 = (h2 * 0xff51afd7ed558ccd) & _MASK64
    h2 ^= (h2 >> 33)
    return (h1 + i * h2) % size


# ---------- BloomFilter ----------

_MAGIC = b"TBLM"
_VERSION_BYTES = struct.pack("<H", 1)


class BloomFilter:
    """Space-efficient probabilistic membership filter.

    Args:
        capacity: Expected number of distinct items.
        error_rate: Target false-positive probability (e.g. 0.001 = 0.1%).
        filepath: If provided, load from this file instead of allocating new.
    """

    __slots__ = ("_bits", "_size", "_hash_count", "_items", "_stats_cache")

    def __init__(self, capacity=100_000, error_rate=0.01, *, filepath=None):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if not (0.0001 <= error_rate <= 0.5):
            raise ValueError("error_rate must be in (0.0001, 0.5)")
        if filepath is not None:
            self._load(filepath)
            return
        size_bits = int(math.ceil(-capacity * math.log(error_rate) / (math.log(2) ** 2)))
        hash_count = max(1, int(round((size_bits / capacity) * math.log(2))))
        size_bits = ((size_bits + 63) // 64) * 64
        self._bits = bytearray(size_bits // 8)
        self._size = size_bits
        self._hash_count = hash_count
        self._items = 0
        self._stats_cache = None

    @classmethod
    def from_bytes(cls, data):
        """Build a BloomFilter from raw serialized bytes (no I/O)."""
        bf = cls.__new__(cls)
        bf._load_bytes(data)
        return bf

    @property
    def size_bits(self):
        return self._size

    @property
    def size_bytes(self):
        return len(self._bits)

    @property
    def hash_count(self):
        return self._hash_count

    @property
    def items(self):
        """Rough count of distinct items added (may overcount on collisions)."""
        return self._items

    def add(self, key):
        """Add a key to the filter."""
        for i in range(self._hash_count):
            idx = _double_hash(key, i, self._size)
            self._set_bit(idx)
        self._items += 1
        self._stats_cache = None

    def add_many(self, keys):
        """Add a batch of keys. Returns the number added."""
        before = self._items
        for k in keys:
            self.add(k)
        return self._items - before

    def __contains__(self, key):
        for i in range(self._hash_count):
            idx = _double_hash(key, i, self._size)
            if not self._get_bit(idx):
                return False
        return True

    def may_contain(self, key):
        """Synonym for `key in filter`; named to avoid double-negatives."""
        return key in self

    def estimated_fpp(self):
        """Current false-positive probability given items additions.

        Uses the standard formula: (1 - exp(-k * n / m))^k
        """
        if self._items == 0:
            return 0.0
        return (1.0 - math.exp(-self._hash_count * self._items / self._size)) ** self._hash_count

    @property
    def stats(self):
        if self._stats_cache is None:
            self._stats_cache = {
                "size_bits": self._size,
                "size_bytes": len(self._bits),
                "hash_count": self._hash_count,
                "items": self._items,
                "fill_ratio": self._fill_ratio(),
                "estimated_fpp": self.estimated_fpp(),
            }
        return dict(self._stats_cache)

    def _fill_ratio(self):
        sample = min(len(self._bits), 4096)
        if sample == 0:
            return 0.0
        c = 0
        for i in range(sample):
            c += bin(self._bits[i]).count("1")
        return (c / (sample * 8)) * (len(self._bits) / max(sample, 1))

    def save(self, filepath):
        """Write the filter to disk."""
        with open(filepath, "wb") as f:
            f.write(_MAGIC)
            f.write(_VERSION_BYTES)
            f.write(struct.pack("<Q", self._size))
            f.write(struct.pack("<H", self._hash_count))
            f.write(struct.pack("<Q", self._items))
            f.write(struct.pack("<Q", len(self._bits)))
            f.write(bytes(self._bits))

    def to_bytes(self):
        """Serialize to bytes (no I/O)."""
        return (
            _MAGIC
            + _VERSION_BYTES
            + struct.pack("<Q", self._size)
            + struct.pack("<H", self._hash_count)
            + struct.pack("<Q", self._items)
            + struct.pack("<Q", len(self._bits))
            + bytes(self._bits)
        )

    @classmethod
    def load(cls, filepath):
        """Load a previously saved filter."""
        bf = cls.__new__(cls)
        bf._load(filepath)
        return bf

    def _load(self, filepath):
        with open(filepath, "rb") as f:
            data = f.read()
        self._load_bytes(data)

    def _load_bytes(self, data):
        if len(data) < 4 + 2 + 8 + 2 + 8 + 8:
            raise ValueError("invalid Bloom filter file: too short")
        if data[:4] != _MAGIC:
            raise ValueError("invalid magic bytes; not a tiny-bloom file")
        version = struct.unpack("<H", data[4:6])[0]
        if version != 1:
            raise ValueError("unsupported tiny-bloom version: " + str(version))
        off = 6
        self._size = struct.unpack("<Q", data[off:off + 8])[0]; off += 8
        self._hash_count = struct.unpack("<H", data[off:off + 2])[0]; off += 2
        self._items = struct.unpack("<Q", data[off:off + 8])[0]; off += 8
        payload_len = struct.unpack("<Q", data[off:off + 8])[0]; off += 8
        if len(data) < off + payload_len:
            raise ValueError("invalid Bloom filter file: truncated payload")
        self._bits = bytearray(data[off:off + payload_len])
        self._stats_cache = None

    def _set_bit(self, idx):
        self._bits[idx >> 3] |= 1 << (idx & 7)

    def _get_bit(self, idx):
        return bool(self._bits[idx >> 3] & (1 << (idx & 7)))

    def __len__(self):
        return self._items

    def __repr__(self):
        return (
            "BloomFilter(size_bits=" + str(self._size)
            + ", hash_count=" + str(self._hash_count)
            + ", items=" + str(self._items)
            + ", est_fpp=" + ("%.2e" % self.estimated_fpp()) + ")"
        )


# ---------- Convenience ----------


def from_iterable(items, *, capacity=100_000, error_rate=0.01):
    """Build a filter and add all items in one go. Capacity is a target upper bound."""
    bf = BloomFilter(capacity=capacity, error_rate=error_rate)
    bf.add_many(items)
    return bf


__all__ = ["BloomFilter", "from_iterable", "__version__"]
