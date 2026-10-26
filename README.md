# tiny-bloom - Zero-Dependency Bloom Filter

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)](tiny_bloom.py)
[![Version](https://img.shields.io/badge/version-0.1.0-blue)](https://github.com/hussain-alsaibai/tiny-bloom)

A Bloom filter is a probabilistic set: it can tell you with certainty that
an element is NOT in the set, but may say it IS when it is not (a false
positive). The probability of a false positive is bounded and tunable.
tiny-bloom is one file, zero dependencies, MIT-licensed, and uses optimal
sizing (m = -n ln p / (ln 2)^2).

## Features

- Zero dependencies - pure stdlib math + struct
- Single file - drop tiny_bloom.py anywhere
- Optimal sizing - auto-computes bit count and hash count for your target FPP
- Serializable - save() / load() and to_bytes() / from_bytes()
- Fast - FNV-1a 64-bit hash + Kirsch-Mitzenmacher double hashing
- Stats - bf.stats shows fill ratio, estimated FPP, item count
- Scalable - handles billions of items at ~2 bits per element (1% FPP)

## Usage

```python
from tiny_bloom import BloomFilter

bf = BloomFilter(capacity=1_000_000, error_rate=0.001)
bf.add("user_42")
bf.add("user_99")

assert "user_42" in bf
assert "user_77" not in bf

print(bf.stats)
bf.save("seen.bin")
bf2 = BloomFilter.load("seen.bin")
assert "user_42" in bf2
```

## Bulk

```python
from tiny_bloom import from_iterable
urls = [...]  # list of URLs
seen = from_iterable(urls, capacity=len(urls), error_rate=0.001)
if url not in seen:
    fetch(url)
    seen.add(url)
```

## How it works

Bit count m for capacity n and target FPP p:

    m = -n * ln(p) / (ln 2)^2
    k = (m / n) * ln 2         (hash count)

For each op we run k "hashes" by computing two real hashes (h1 = FNV-1a(key),
h2 = splitmix64(h1)) then h_i = (h1 + i * h2) mod m. This is the
Kirsch-Mitzenmacher 2006 double-hashing trick - O(1) per op, no separate
hash functions needed.

## When to use

- Use tiny-bloom when the set is huge and false positives are tolerable
- Use a HashSet (set) when memory is abundant and you need zero false positives
- Use a Redis SET when you need cross-process state and exact answers

## Tests

```bash
python -m unittest test_tiny_bloom.py -v
```

## License

MIT
