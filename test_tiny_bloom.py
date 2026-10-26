"""Tests for tiny-bloom. Run with: python -m unittest test_tiny_bloom.py -v"""

from __future__ import annotations

import math
import os
import random
import tempfile
import unittest

from tiny_bloom import BloomFilter, from_iterable, __version__


class TestVersion(unittest.TestCase):
    def test_version(self):
        self.assertEqual(__version__, "0.1.0")


class TestConstruction(unittest.TestCase):
    def test_basic_sizing(self):
        bf = BloomFilter(capacity=10_000, error_rate=0.01)
        # m = -n*ln(p) / (ln 2)^2 = 95851 bits for n=10000, p=0.01.
        # Tiny rounds up to a multiple of 64, so allow slack.
        s = bf.stats
        self.assertGreater(s["size_bits"], 95000)
        self.assertLess(s["size_bits"], 96000)
        self.assertGreaterEqual(s["hash_count"], 6)
        self.assertLessEqual(s["hash_count"], 8)

    def test_invalid_capacity(self):
        with self.assertRaises(ValueError):
            BloomFilter(capacity=0)
        with self.assertRaises(ValueError):
            BloomFilter(capacity=-1)

    def test_invalid_error_rate(self):
        with self.assertRaises(ValueError):
            BloomFilter(error_rate=0.0)
        with self.assertRaises(ValueError):
            BloomFilter(error_rate=0.6)
        with self.assertRaises(ValueError):
            BloomFilter(error_rate=-0.1)

    def test_repr(self):
        bf = BloomFilter(capacity=100, error_rate=0.01)
        s = repr(bf)
        self.assertIn("BloomFilter", s)
        self.assertIn("size_bits=", s)


class TestMembership(unittest.TestCase):
    def test_no_false_negatives(self):
        bf = BloomFilter(capacity=10_000, error_rate=0.001)
        for i in range(1000):
            bf.add(f"item-{i}")
        for i in range(1000):
            self.assertIn(f"item-{i}", bf)

    def test_missing_returns_false(self):
        bf = BloomFilter(capacity=1000, error_rate=0.01)
        bf.add("a")
        self.assertNotIn("b", bf)
        self.assertNotIn("c", bf)

    def test_may_contain_alias(self):
        bf = BloomFilter(capacity=10, error_rate=0.01)
        bf.add("x")
        self.assertTrue(bf.may_contain("x"))
        # may_contain returns False for definitely-not, but true for FPs
        self.assertFalse(bf.may_contain("x-not-here"))

    def test_bytes_input(self):
        bf = BloomFilter(capacity=100, error_rate=0.01)
        bf.add(b"bytes-key-1")
        bf.add("str-key-2")
        self.assertIn(b"bytes-key-1", bf)
        self.assertIn("str-key-2", bf)


class TestFPP(unittest.TestCase):
    def test_no_items_zero_fpp(self):
        bf = BloomFilter(capacity=1000, error_rate=0.01)
        self.assertEqual(bf.estimated_fpp(), 0.0)

    def test_measured_fpp_within_tolerance(self):
        """Empirical FPP for 1000 items added to a 10K-capacity filter at 1% target."""
        bf = BloomFilter(capacity=10_000, error_rate=0.01)
        for i in range(1000):
            bf.add(f"a-{i}")
        # Probe with keys we KNOW we did not add
        false_positives = 0
        probes = 5000
        for i in range(probes):
            if bf.may_contain(f"b-{i}"):
                false_positives += 1
        observed_fpp = false_positives / probes
        # Should be very close to 1%, allow generous slack for small samples
        # but must not exceed 3%.
        self.assertLess(observed_fpp, 0.03, f"FPP {observed_fpp} too high")

    def test_fpp_increases_with_items(self):
        bf = BloomFilter(capacity=1000, error_rate=0.01)
        fpps = []
        added = 0
        for n in (100, 500, 1000, 1500):  # last is over capacity
            for i in range(n - added):
                bf.add(f"k-{added}-{i}")
            added = n
            fpps.append(bf.estimated_fpp())
        # FPP should be monotonically increasing (modulo specifics)
        self.assertLess(fpps[0], fpps[-1])


class TestSizingMath(unittest.TestCase):
    def test_optimal_m_lower_bound(self):
        """m must be at least ceil(-n ln p / (ln 2)^2)."""
        for n, p in [(100, 0.01), (1000, 0.001), (10_000, 0.0001)]:
            bf = BloomFilter(capacity=n, error_rate=p)
            m = bf.size_bits
            # Tiny rounds up to multiple of 64, so allow slack
            expected = -n * math.log(p) / (math.log(2) ** 2)
            self.assertGreaterEqual(m, math.ceil(expected))
            self.assertLess(m, math.ceil(expected) + 128)

    def test_hash_count_in_optimal_range(self):
        bf = BloomFilter(capacity=1000, error_rate=0.01)
        # k = (m/n) * ln 2  ≈ 7 for 1% / 1000
        self.assertGreaterEqual(bf.hash_count, 5)
        self.assertLessEqual(bf.hash_count, 9)


class TestBulk(unittest.TestCase):
    def test_add_many_returns_count(self):
        bf = BloomFilter(capacity=100, error_rate=0.01)
        n = bf.add_many([f"k-{i}" for i in range(50)])
        self.assertEqual(n, 50)
        self.assertEqual(bf.items, 50)

    def test_from_iterable(self):
        items = [f"u-{i}" for i in range(200)]
        bf = from_iterable(items, capacity=200, error_rate=0.001)
        for item in items:
            self.assertIn(item, bf)
        self.assertEqual(bf.items, 200)


class TestSerialization(unittest.TestCase):
    def test_save_load(self):
        bf = BloomFilter(capacity=1000, error_rate=0.01)
        for i in range(100):
            bf.add(f"k-{i}")
        with tempfile.NamedTemporaryFile(suffix=".bloom", delete=False) as f:
            p = f.name
        try:
            bf.save(p)
            bf2 = BloomFilter.load(p)
            for i in range(100):
                self.assertIn(f"k-{i}", bf2)
            self.assertEqual(bf2.size_bits, bf.size_bits)
            self.assertEqual(bf2.hash_count, bf.hash_count)
            self.assertEqual(bf2.items, bf.items)
        finally:
            os.unlink(p)

    def test_to_from_bytes(self):
        bf = BloomFilter(capacity=1000, error_rate=0.01)
        for i in range(100):
            bf.add(f"k-{i}")
        data = bf.to_bytes()
        self.assertGreater(len(data), 100)
        self.assertEqual(data[:4], b"TBLM")
        bf2 = BloomFilter.from_bytes(data)
        for i in range(100):
            self.assertIn(f"k-{i}", bf2)

    def test_invalid_magic(self):
        with self.assertRaises(ValueError):
            BloomFilter.from_bytes(b"XXXX" + b"\x00" * 100)

    def test_truncated(self):
        with self.assertRaises(ValueError):
            BloomFilter.from_bytes(b"TBLM" + b"\x00" * 3)


class TestLarge(unittest.TestCase):
    def test_no_false_negatives_at_100k(self):
        bf = BloomFilter(capacity=100_000, error_rate=0.001)
        for i in range(100_000):
            bf.add(f"user-{i}")
        for i in range(100_000):
            self.assertIn(f"user-{i}", bf)

    def test_smoke_random(self):
        random.seed(42)
        bf = BloomFilter(capacity=10_000, error_rate=0.001)
        # Insert 5000 distinct items
        added = set()
        while len(added) < 5000:
            x = f"item-{random.randrange(1_000_000)}"
            added.add(x)
            bf.add(x)
        # Verify all added are present
        for x in added:
            self.assertIn(x, bf)
        # Probe with a new random set; count FPs
        fp = 0
        probes = 5000
        for _ in range(probes):
            x = f"probe-{random.randrange(10_000_000)}"
            if x in added:
                continue
            if x in bf:
                fp += 1
        observed = fp / probes
        # Target 0.1%, allow generous slack (max 3% in this small sample)
        self.assertLess(observed, 0.03)


if __name__ == "__main__":
    unittest.main(verbosity=2)
