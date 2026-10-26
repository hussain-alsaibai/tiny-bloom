# Changelog

All notable changes to tiny-bloom are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-10-26

First release.

### Added
- `BloomFilter` with optimal sizing: `m = -n ln(p) / (ln 2)^2` bits, rounded
  up to a multiple of 64, with `k = round(m/n * ln 2)` hash functions.
- FNV-1a 64-bit hash with Kirsch-Mitzenmacher double hashing.
- `add()`, `add_many()`, `__contains__()`, `may_contain()`.
- `save()` / `load()` and `to_bytes()` / `from_bytes()` for persistence.
- `stats` property: item count, bit count, byte count, hash count, fill
  ratio, estimated FPP.
- `from_iterable()` convenience constructor.

### Fixed
- Two tests asserted the wrong thing and had been failing since the
  package was first written:
  - `test_basic_sizing` compared a **bit** count against a byte-scale
    bound (9000-12000) when the correct value is 95851 bits for
    `capacity=10000, error_rate=0.01`. The implementation was right; the
    bound was wrong.
  - `test_fpp_increases_with_items` subtracted an FPP (a float) from an
    item count, raising `TypeError: 'float' object cannot be interpreted
    as an integer`. It now tracks how many items have been added.

### Changed
- The implementation itself was correct and is unchanged.
- Added CI across Python 3.8-3.12.

