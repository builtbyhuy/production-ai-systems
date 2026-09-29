"""Build the original MIT-licensed Pais Python Maintenance v1 corpus.

Every entry specifies an independently chosen maintenance contract, a reference,
one seeded regression, and executable examples. No external dataset is copied.
Do not execute untrusted submissions here; the generated references are our code.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

TASKS: list[dict] = []


def c(args, expected=None, raises=None):
    result = {"args": args}
    result["raises" if raises else "expected"] = raises or expected
    return result


def add(slug, category, difficulty, description, reference, mutation, cases):
    if reference.count(mutation[0]) != 1:
        raise ValueError(f"Regression mutation must match one unique source span: {slug}")
    starter = reference.replace(*mutation, 1)
    TASKS.append(
        {
            "id": f"ppm-{len(TASKS) + 1:03d}-{slug}",
            "version": "1.0.0",
            "source_id": f"pais-authored/{slug}",
            "source_revision": "2026-09-29-v1",
            "license": "MIT",
            "category": category,
            "difficulty": difficulty,
            "split": "train" if len(TASKS) % 10 < 6 else "dev" if len(TASKS) % 10 < 8 else "test",
            "title": slug.replace("-", " ").title(),
            "prompt": description
            + " Repair solve, preserving its signature. Return only a Python module.",
            "entrypoint": "solve",
            "starter": starter,
            "reference": reference,
            "cases": cases,
            "provenance": "Original synthetic maintenance contract and seeded regression authored for this repository; no mined issue or external solution.",
        }
    )


# Collections: order, missing values, mutation, and shape contracts.
add(
    "stable-dedup",
    "collections",
    "easy",
    "Deduplicate hashable values while preserving their first appearance.",
    "def solve(values):\n    return list(dict.fromkeys(values))\n",
    ("list(dict.fromkeys(values))", "sorted(set(values))"),
    [c([[3, 1, 3, 2]], [3, 1, 2]), c([[]], []), c([[0, 0, -1]], [0, -1])],
)
add(
    "chunk-tail",
    "collections",
    "easy",
    "Split a sequence into chunks of at most size, retain the final short chunk, and reject nonpositive size.",
    "def solve(values, size):\n    if size <= 0: raise ValueError('size')\n    return [values[i:i+size] for i in range(0, len(values), size)]\n",
    ("len(values), size", "len(values)-size+1, size"),
    [
        c([[1, 2, 3, 4, 5], 2], [[1, 2], [3, 4], [5]]),
        c([[], 3], []),
        c([[1], 0], raises="ValueError"),
    ],
)
add(
    "flatten-one",
    "collections",
    "easy",
    "Flatten exactly one list level; nested elements inside each immediate list must retain their structure.",
    "def solve(groups):\n    return [value for group in groups for value in group]\n",
    ("for group in groups for value in group", "for group in groups[:1] for value in group"),
    [c([[[1], [2, 3]]], [1, 2, 3]), c([[[], [4], []]], [4]), c([[[[1]], [2]]], [[1], 2])],
)
add(
    "group-missing-key",
    "collections",
    "medium",
    "Group records by the requested key, putting records without that key under null instead of dropping them.",
    "def solve(records, key):\n    result = {}\n    for row in records:\n        value = row.get(key)\n        result.setdefault(value, []).append(row)\n    return list(result.items())\n",
    ("row.get(key)", "row[key]"),
    [
        c([[{"x": "a"}, {"y": 2}], "x"], [["a", [{"x": "a"}]], [None, [{"y": 2}]]]),
        c([[], "x"], []),
        c([[{"x": 0}, {"x": 0}], "x"], [[0, [{"x": 0}, {"x": 0}]]]),
    ],
)
add(
    "merge-list-settings",
    "collections",
    "medium",
    "Merge dictionary list values in left-to-right order without modifying either input and retain keys occurring on one side only.",
    "def solve(left, right):\n    keys = dict.fromkeys([*left, *right])\n    return {key: left.get(key, []) + right.get(key, []) for key in keys}\n",
    ("[*left, *right]", "[*left]"),
    [
        c([{"a": [1]}, {"a": [2], "b": [3]}], {"a": [1, 2], "b": [3]}),
        c([{}, {"x": []}], {"x": []}),
        c([{"x": [0]}, {}], {"x": [0]}),
    ],
)
add(
    "latest-record-wins",
    "collections",
    "medium",
    "Return the last record per id while retaining the order in which ids first appeared.",
    "def solve(records):\n    result = {}\n    for record in records:\n        result[record['id']] = record\n    return list(result.values())\n",
    ("result[record['id']] = record", "result.setdefault(record['id'], record)"),
    [
        c(
            [[{"id": "a", "v": 1}, {"id": "b", "v": 2}, {"id": "a", "v": 3}]],
            [{"id": "a", "v": 3}, {"id": "b", "v": 2}],
        ),
        c([[]], []),
        c([[{"id": 0}]], [{"id": 0}]),
    ],
)
add(
    "interleave-uneven",
    "collections",
    "medium",
    "Alternate elements of two lists, retaining all elements from the longer list.",
    "def solve(left, right):\n    out = []\n    for i in range(max(len(left), len(right))):\n        if i < len(left): out.append(left[i])\n        if i < len(right): out.append(right[i])\n    return out\n",
    ("max(len(left), len(right))", "min(len(left), len(right))"),
    [c([[1, 2, 3], [4]], [1, 4, 2, 3]), c([[], [8]], [8]), c([[1], [2]], [1, 2])],
)
add(
    "complete-windows",
    "collections",
    "medium",
    "Return every contiguous full window of width size; return no windows when size exceeds the input and reject size <= 0.",
    "def solve(values, size):\n    if size <= 0: raise ValueError('size')\n    return [values[i:i+size] for i in range(len(values)-size+1)]\n",
    ("len(values)-size+1", "len(values)-size"),
    [
        c([[1, 2, 3], 2], [[1, 2], [2, 3]]),
        c([[1], 1], [[1]]),
        c([[1], 2], []),
        c([[], 0], raises="ValueError"),
    ],
)
add(
    "preserve-falsey-values",
    "collections",
    "easy",
    "Remove only null values; keep zero, false, empty strings, and empty containers.",
    "def solve(values):\n    return [value for value in values if value is not None]\n",
    ("value is not None", "value"),
    [c([[0, False, "", None, [], 3]], [0, False, "", [], 3]), c([[None]], []), c([[]], [])],
)
add(
    "nested-default",
    "collections",
    "medium",
    "Look up a nested dictionary path; use the default only for a missing key or non-dictionary intermediate, including an empty path returning the input.",
    "def solve(data, path, default):\n    current = data\n    for key in path:\n        if not isinstance(current, dict) or key not in current: return default\n        current = current[key]\n    return current\n",
    ("return current\n", "return current or default\n"),
    [c([{"a": {"b": 0}}, ["a", "b"], 9], 0), c([{"a": 1}, ["a", "b"], 9], 9), c([{}, [], 9], {})],
)

# Text: representation changes that commonly break API contracts.
add(
    "split-assignment-once",
    "text",
    "easy",
    "Parse key=value at the first equals sign, preserving further equals signs in the value and raising ValueError when no separator exists.",
    "def solve(text):\n    key, value = text.split('=', 1)\n    return [key, value]\n",
    ("text.split('=', 1)", "text.split('=')"),
    [c(["token=a=b"], ["token", "a=b"]), c(["a="], ["a", ""]), c(["none"], raises="ValueError")],
)
add(
    "remove-exact-prefix",
    "text",
    "easy",
    "Remove the literal prefix once when present; do not strip an arbitrary set of characters.",
    "def solve(text, prefix):\n    return text.removeprefix(prefix)\n",
    ("text.removeprefix(prefix)", "text.lstrip(prefix)"),
    [
        c(["token:tenant", "token:"], "tenant"),
        c(["ttoken", "token"], "ttoken"),
        c(["abc", ""], "abc"),
    ],
)
add(
    "unicode-caseless-id",
    "text",
    "medium",
    "Compare user-visible identifiers with Unicode case folding after trimming surrounding whitespace.",
    "def solve(left, right):\n    return left.strip().casefold() == right.strip().casefold()\n",
    ("left.strip().casefold()", "left.strip().lower()"),
    [c(["Straße", "STRASSE"], True), c([" X ", "x"], True), c(["a", "b"], False)],
)
add(
    "remove-exact-suffix",
    "text",
    "easy",
    "Remove a filename suffix literally and once; leave names without that suffix unchanged.",
    "def solve(name, suffix):\n    return name.removesuffix(suffix)\n",
    ("name.removesuffix(suffix)", "name.rstrip(suffix)"),
    [
        c(["report.csv", ".csv"], "report"),
        c(["class.csv", ".csv"], "class"),
        c(["report.txt", ".csv"], "report.txt"),
    ],
)
add(
    "normalize-whitespace",
    "text",
    "easy",
    "Collapse any run of Unicode whitespace to one ASCII space and strip outer whitespace.",
    "def solve(text):\n    return ' '.join(text.split())\n",
    ("text.split()", "text.split(' ')"),
    [c(["  alpha\t beta\n gamma  "], "alpha beta gamma"), c(["a\u00a0b"], "a b"), c([""], "")],
)
add(
    "parse-quoted-csv",
    "text",
    "medium",
    "Parse a single RFC-style CSV record including quoted commas and escaped quotes; return an empty list for empty input.",
    "import csv\nimport io\ndef solve(text):\n    return next(csv.reader(io.StringIO(text)), [])\n",
    ("next(csv.reader(io.StringIO(text)), [])", "text.split(',')"),
    [c(['a,"b,c",d'], ["a", "b,c", "d"]), c(['"a""b",c'], ['a"b', "c"]), c([""], [])],
)
add(
    "query-blank-values",
    "text",
    "medium",
    "Parse a query string into key-to-list mappings, preserving repeated keys and blank values.",
    "from urllib.parse import parse_qs\ndef solve(query):\n    return parse_qs(query, keep_blank_values=True)\n",
    ("keep_blank_values=True", "keep_blank_values=False"),
    [c(["a=1&a=2&b="], {"a": ["1", "2"], "b": [""]}), c(["q=a+b"], {"q": ["a b"]}), c([""], {})],
)
add(
    "unicode-slug",
    "text",
    "medium",
    "Create an ASCII slug by removing combining accents, lowercasing, replacing nonalphanumeric runs with hyphens, and trimming hyphens.",
    "import re\nimport unicodedata\ndef solve(text):\n    plain = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()\n    return re.sub(r'[^a-z0-9]+', '-', plain.lower()).strip('-')\n",
    ("normalize('NFKD', text)", "normalize('NFC', text)"),
    [c(["Café Crème"], "cafe-creme"), c(["  API_v2! "], "api-v2"), c(["---"], "")],
)
add(
    "redact-account-tail",
    "text",
    "easy",
    "Replace all but the final four characters with stars, leaving strings of length four or less unchanged.",
    "def solve(value):\n    return '*' * max(0, len(value)-4) + value[-4:]\n",
    ("value[-4:]", "value[:4]"),
    [c(["12345678"], "****5678"), c(["123"], "123"), c([""], "")],
)
add(
    "whole-word-replacement",
    "text",
    "medium",
    "Replace a literal whole word using regex word boundaries; replacement text and search text may contain regex metacharacters.",
    "import re\ndef solve(text, word, replacement):\n    return re.sub(r'\\b' + re.escape(word) + r'\\b', lambda match: replacement, text)\n",
    ("re.escape(word)", "word"),
    [
        c(["a.b aXb", "a.b", "X"], "X aXb"),
        c(["cat scatter cat", "cat", "dog"], "dog scatter dog"),
        c(["x x", "x", r"\1"], r"\1 \1"),
    ],
)

# Numeric invariants: exact money, bounds, and defined empty behavior.
add(
    "weighted-mean",
    "numeric",
    "medium",
    "Compute the weighted mean, returning null when total weight is zero and rejecting negative weights or unequal lengths.",
    "def solve(values, weights):\n    if len(values) != len(weights) or any(w < 0 for w in weights): raise ValueError('weights')\n    total = sum(weights)\n    return sum(v*w for v,w in zip(values,weights))/total if total else None\n",
    ("sum(weights)", "len(weights)"),
    [
        c([[10, 20], [1, 3]], 17.5),
        c([[7], [0]], None),
        c([[1], [-1]], raises="ValueError"),
        c([[1], []], raises="ValueError"),
    ],
)
add(
    "clamp-order",
    "numeric",
    "easy",
    "Clamp a number to inclusive lower/upper bounds and reject reversed bounds.",
    "def solve(value, low, high):\n    if low > high: raise ValueError('bounds')\n    return min(high, max(low, value))\n",
    ("min(high, max(low, value))", "max(high, min(low, value))"),
    [c([5, 0, 10], 5), c([-1, 0, 10], 0), c([20, 0, 10], 10), c([1, 3, 2], raises="ValueError")],
)
add(
    "even-median",
    "numeric",
    "easy",
    "Return the median of an unsorted numeric list; average both middle values for even lengths and reject empty input.",
    "def solve(values):\n    if not values: raise ValueError('empty')\n    data = sorted(values)\n    n = len(data)\n    return data[n//2] if n%2 else (data[n//2-1]+data[n//2])/2\n",
    ("(data[n//2-1]+data[n//2])/2", "data[n//2]"),
    [c([[4, 1, 2, 3]], 2.5), c([[8, 1, 3]], 3), c([[]], raises="ValueError")],
)
add(
    "nearest-rank-percentile",
    "numeric",
    "medium",
    "Compute the nearest-rank percentile for 0 < p <= 100 using a one-indexed ceiling rank; reject empty data or invalid p.",
    "import math\ndef solve(values, p):\n    if not values or not 0 < p <= 100: raise ValueError('percentile')\n    return sorted(values)[math.ceil(p*len(values)/100)-1]\n",
    ("math.ceil(p*len(values)/100)-1", "min(len(values)-1, math.ceil(p*len(values)/100))"),
    [c([[1, 2, 3, 4], 50], 2), c([[8], 100], 8), c([[1, 2], 0], raises="ValueError")],
)
add(
    "zero-denominator-policy",
    "numeric",
    "easy",
    "Return a ratio, using the provided default only when denominator is zero; preserve a legitimate zero numerator result.",
    "def solve(numerator, denominator, default):\n    return numerator / denominator if denominator != 0 else default\n",
    ("denominator != 0", "numerator != 0"),
    [c([0, 4, 99], 0), c([4, 0, 99], 99), c([9, 3, 99], 3)],
)
add(
    "decimal-money-rounding",
    "numeric",
    "medium",
    "Convert a decimal amount string to two decimal places using ROUND_HALF_UP, returning a fixed-point string.",
    "from decimal import Decimal, ROUND_HALF_UP\ndef solve(amount):\n    return format(Decimal(amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), '.2f')\n",
    ("Decimal(amount)", "Decimal(float(amount))"),
    [c(["2.675"], "2.68"), c(["1"], "1.00"), c(["-1.005"], "-1.01")],
)
add(
    "integer-ceiling-division",
    "numeric",
    "easy",
    "Return mathematical ceiling division for integer a and positive integer b; reject nonpositive b.",
    "def solve(a, b):\n    if b <= 0: raise ValueError('divisor')\n    return -(-a//b)\n",
    ("-(-a//b)", "a//b"),
    [c([7, 3], 3), c([-7, 3], -2), c([0, 3], 0), c([1, 0], raises="ValueError")],
)
add(
    "bounded-exponential-backoff",
    "numeric",
    "medium",
    "Return min(cap, base*2**attempt), where attempt starts at zero; reject negative base, cap, or attempt.",
    "def solve(base, attempt, cap):\n    if min(base, attempt, cap) < 0: raise ValueError('negative')\n    return min(cap, base * 2**attempt)\n",
    ("min(cap, base * 2**attempt)", "max(cap, base * 2**attempt)"),
    [c([1, 0, 10], 1), c([2, 5, 10], 10), c([1, -1, 10], raises="ValueError")],
)
add(
    "reserve-microcents",
    "numeric",
    "medium",
    "Reserve the ceiling of exact decimal unit price times nonnegative token count as an integer; reject negative tokens or price.",
    "from decimal import Decimal, ROUND_CEILING\ndef solve(tokens, unit_price):\n    price = Decimal(unit_price)\n    if tokens < 0 or price < 0: raise ValueError('negative')\n    return int((tokens * price).to_integral_value(rounding=ROUND_CEILING))\n",
    ("rounding=ROUND_CEILING", "rounding='ROUND_FLOOR'"),
    [c([3, "0.2"], 1), c([10, "0.2"], 2), c([0, "0.2"], 0), c([-1, "1"], raises="ValueError")],
)
add(
    "population-variance",
    "numeric",
    "medium",
    "Compute population variance, including zero variance for a singleton; reject an empty population.",
    "def solve(values):\n    if not values: raise ValueError('empty')\n    mean = sum(values)/len(values)\n    return sum((x-mean)**2 for x in values)/len(values)\n",
    ("for x in values)/len(values)", "for x in values)/(len(values)-1)"),
    [c([[1, 3]], 1), c([[4]], 0), c([[]], raises="ValueError")],
)

# Time contracts use explicit supplied clocks, never wall-clock sleeps.
add(
    "utc-offset-conversion",
    "time",
    "medium",
    "Convert an ISO timestamp with offset to UTC ISO form ending in Z. Treat a naive timestamp as UTC.",
    "from datetime import datetime, timezone\ndef solve(value):\n    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))\n    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)\n    return dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')\n",
    ("dt.astimezone(timezone.utc)", "dt.replace(tzinfo=timezone.utc)"),
    [
        c(["2026-01-01T07:00:00+07:00"], "2026-01-01T00:00:00Z"),
        c(["2026-01-01T00:00:00"], "2026-01-01T00:00:00Z"),
        c(["2025-12-31T19:00:00-05:00"], "2026-01-01T00:00:00Z"),
    ],
)
add(
    "retry-after-nonnegative",
    "time",
    "easy",
    "Return whole seconds until retry_at by ceiling positive remaining time, or zero once its deadline has passed.",
    "import math\ndef solve(now, retry_at):\n    return max(0, math.ceil(retry_at-now))\n",
    ("max(0, math.ceil(retry_at-now))", "int(retry_at-now)"),
    [c([10, 10.2], 1), c([12, 10], 0), c([10, 13], 3)],
)
add(
    "epoch-millisecond-scale",
    "time",
    "easy",
    "Convert integer milliseconds since Unix epoch to UTC ISO timestamp, retaining millisecond precision.",
    "from datetime import datetime, timezone\ndef solve(milliseconds):\n    return datetime.fromtimestamp(milliseconds/1000, tz=timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')\n",
    ("milliseconds/1000", "milliseconds"),
    [
        c([1500], "1970-01-01T00:00:01.500Z"),
        c([0], "1970-01-01T00:00:00.000Z"),
        c([-1], "1969-12-31T23:59:59.999Z"),
    ],
)
add(
    "half-open-overlap",
    "time",
    "medium",
    "Determine whether nonempty half-open intervals [a,b) and [c,d) overlap; reject reversed bounds.",
    "def solve(a,b,c,d):\n    if a>b or c>d: raise ValueError('interval')\n    return max(a,c) < min(b,d)\n",
    ("max(a,c) < min(b,d)", "max(a,c) <= min(b,d)"),
    [
        c([1, 2, 2, 3], False),
        c([1, 3, 2, 4], True),
        c([1, 1, 0, 2], False),
        c([3, 1, 0, 2], raises="ValueError"),
    ],
)
add(
    "ttl-expiry-boundary",
    "time",
    "easy",
    "An item is valid only while now is strictly earlier than created + ttl; zero/negative ttl immediately expires.",
    "def solve(created, ttl, now):\n    return ttl > 0 and now < created + ttl\n",
    ("now < created + ttl", "now <= created + ttl"),
    [c([10, 5, 15], False), c([10, 5, 14], True), c([10, 0, 9], False)],
)
add(
    "calendar-day-increment",
    "time",
    "easy",
    "Add a signed number of calendar days to an ISO date, including month/year/leap-day rollover.",
    "from datetime import date, timedelta\ndef solve(value, days):\n    return (date.fromisoformat(value)+timedelta(days=days)).isoformat()\n",
    ("timedelta(days=days)", "timedelta(seconds=days)"),
    [
        c(["2024-02-28", 1], "2024-02-29"),
        c(["2025-12-31", 1], "2026-01-01"),
        c(["2026-01-01", -1], "2025-12-31"),
    ],
)
add(
    "iso-week-year",
    "time",
    "medium",
    "Return ISO week-year and week number for a date, which may differ from the calendar year around New Year.",
    "from datetime import date\ndef solve(value):\n    day = date.fromisoformat(value)\n    year, week, _ = day.isocalendar()\n    return [year, week]\n",
    ("return [year, week]", "return [day.year, week]"),
    [c(["2021-01-01"], [2020, 53]), c(["2020-12-31"], [2020, 53]), c(["2026-01-05"], [2026, 2])],
)
add(
    "inclusive-date-range",
    "time",
    "medium",
    "List all ISO dates from start through end inclusively; return an empty list for a reversed range.",
    "from datetime import date, timedelta\ndef solve(start, end):\n    first, last = date.fromisoformat(start), date.fromisoformat(end)\n    return [(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)]\n",
    ("(last-first).days+1", "(last-first).days"),
    [
        c(["2026-01-01", "2026-01-03"], ["2026-01-01", "2026-01-02", "2026-01-03"]),
        c(["2026-01-01", "2026-01-01"], ["2026-01-01"]),
        c(["2026-01-03", "2026-01-01"], []),
    ],
)
add(
    "overnight-schedule",
    "time",
    "hard",
    "For minute-of-day values 0..1439, test membership in a half-open active window, including midnight wrapping. Equal endpoints mean an empty window.",
    "def solve(start,end,minute):\n    if any(not 0<=x<1440 for x in (start,end,minute)): raise ValueError('minute')\n    return start<=minute<end if start<=end else minute>=start or minute<end\n",
    ("minute>=start or minute<end", "minute>=start and minute<end"),
    [
        c([1380, 60, 30], True),
        c([1380, 60, 720], False),
        c([60, 120, 120], False),
        c([60, 60, 60], False),
    ],
)
add(
    "duration-includes-days",
    "time",
    "medium",
    "Return elapsed seconds between two ISO datetimes, including full days and negative intervals.",
    "from datetime import datetime\ndef solve(start,end):\n    delta = datetime.fromisoformat(end)-datetime.fromisoformat(start)\n    return delta.total_seconds()\n",
    ("delta.total_seconds()", "delta.seconds"),
    [
        c(["2026-01-01T00:00:00", "2026-01-03T00:00:01"], 172801),
        c(["2026-01-02T00:00:00", "2026-01-01T00:00:00"], -86400),
        c(["2026-01-01T00:00:00", "2026-01-01T00:00:00"], 0),
    ],
)

# Validation: fail-closed schema decisions, exact type and boundary behavior.
add(
    "boolean-is-not-integer",
    "validation",
    "easy",
    "Accept only actual integer counts in the inclusive range 0..100; booleans must be rejected.",
    "def solve(value):\n    return type(value) is int and 0 <= value <= 100\n",
    ("type(value) is int", "isinstance(value, int)"),
    [c([True], False), c([0], True), c([100], True), c([101], False)],
)
add(
    "strict-boolean-parser",
    "validation",
    "easy",
    "Parse case-insensitive true/false strings with outer whitespace; raise ValueError for any other literal.",
    "def solve(text):\n    value = text.strip().lower()\n    if value not in ('true','false'): raise ValueError('boolean')\n    return value == 'true'\n",
    ("value == 'true'", "bool(value)"),
    [c([" false "], False), c(["TRUE"], True), c(["yes"], raises="ValueError")],
)
add(
    "tcp-port-boundaries",
    "validation",
    "easy",
    "Accept non-boolean integer server ports from 1 through 65535 inclusive.",
    "def solve(port):\n    return type(port) is int and 1 <= port <= 65535\n",
    ("1 <= port <= 65535", "0 <= port < 65535"),
    [c([65535], True), c([0], False), c([80], True), c([True], False)],
)
add(
    "required-key-presence",
    "validation",
    "easy",
    "Return names of missing required keys. A present key with null, false, or zero still counts as present.",
    "def solve(payload, required):\n    return [key for key in required if key not in payload]\n",
    ("key not in payload", "not payload.get(key)"),
    [
        c([{"x": None, "y": 0}, ["x", "y", "z"]], ["z"]),
        c([{}, []], []),
        c([{"x": False}, ["x"]], []),
    ],
)
add(
    "bounded-batch-size",
    "validation",
    "easy",
    "Accept nonempty lists containing at most limit items, rejecting other types and nonpositive limits.",
    "def solve(items, limit):\n    return isinstance(items, list) and limit > 0 and 0 < len(items) <= limit\n",
    ("len(items) <= limit", "len(items) < limit"),
    [c([[1, 2], 2], True), c([[], 2], False), c(["ab", 2], False), c([[1], 0], False)],
)
add(
    "ascii-decimal-id",
    "validation",
    "medium",
    "Accept strings consisting of one or more ASCII decimal digits, excluding signs, decimal points, whitespace and non-ASCII digits.",
    "import re\ndef solve(value):\n    return isinstance(value,str) and re.fullmatch(r'[0-9]+',value) is not None\n",
    ("r'[0-9]+'", "r'\\d+'"),
    [c(["123"], True), c(["١٢٣"], False), c(["12\n"], False), c([""], False)],
)
add(
    "required-json-object",
    "validation",
    "medium",
    "Parse JSON and require a top-level object; an empty object is valid but lists, null, invalid JSON and scalar values raise ValueError.",
    "import json\ndef solve(text):\n    value = json.loads(text)\n    if not isinstance(value,dict): raise ValueError('object')\n    return value\n",
    ("not isinstance(value,dict)", "not value"),
    [
        c(["{}"], {}),
        c(["[]"], raises="ValueError"),
        c(["null"], raises="ValueError"),
        c(['{"x":1}'], {"x": 1}),
    ],
)
add(
    "reject-nonfinite-number",
    "validation",
    "medium",
    "Parse a float string and require a finite result; NaN, infinity and overflow-to-infinity raise ValueError.",
    "import math\ndef solve(text):\n    value = float(text)\n    if not math.isfinite(value): raise ValueError('finite')\n    return value\n",
    ("not math.isfinite(value)", "math.isinf(value)"),
    [
        c(["NaN"], raises="ValueError"),
        c(["1e999"], raises="ValueError"),
        c(["1.25"], 1.25),
        c(["-0"], 0),
    ],
)
add(
    "ipv4-validation",
    "validation",
    "medium",
    "Accept canonical IPv4 text using the Python standard library; reject IPv6, out-of-range octets and leading-zero octets.",
    "import ipaddress\ndef solve(text):\n    try: return isinstance(ipaddress.ip_address(text), ipaddress.IPv4Address)\n    except ValueError: return False\n",
    ("ipaddress.IPv4Address", "(ipaddress.IPv4Address, ipaddress.IPv6Address)"),
    [c(["127.0.0.1"], True), c(["::1"], False), c(["256.1.2.3"], False), c(["010.0.0.1"], False)],
)
add(
    "enum-normalization",
    "validation",
    "easy",
    "Normalize a supplied operation by stripping and lowercasing before checking the allowlist; return the normalized operation or raise ValueError.",
    "def solve(value):\n    normalized = value.strip().lower()\n    if normalized not in {'create','read','update','delete'}: raise ValueError('operation')\n    return normalized\n",
    ("value.strip().lower()", "value.lower()"),
    [c([" READ "], "read"), c(["Create"], "create"), c(["drop"], raises="ValueError")],
)

# HTTP semantics are pure functions so fixture checks need no network service.
add(
    "retryable-http-status",
    "http_api",
    "medium",
    "Retry only 408, 429, 500, 502, 503 and 504. Other client errors and success statuses must not retry.",
    "def solve(status):\n    return status in {408,429,500,502,503,504}\n",
    ("status in {408,429,500,502,503,504}", "status >= 400"),
    [c([429], True), c([401], False), c([501], False), c([200], False)],
)
add(
    "encode-repeated-query",
    "http_api",
    "medium",
    "Encode query parameters preserving list values as repeated keys and blank strings as empty values, with insertion order preserved.",
    "from urllib.parse import urlencode\ndef solve(params):\n    return urlencode(params, doseq=True)\n",
    ("doseq=True", "doseq=False"),
    [c([{"tag": ["a", "b"], "q": ""}], "tag=a&tag=b&q="), c([{"q": "a b"}], "q=a+b"), c([{}], "")],
)
add(
    "escape-path-segment",
    "http_api",
    "medium",
    "Percent-encode one opaque URL path segment; embedded slashes must not create new path segments.",
    "from urllib.parse import quote\ndef solve(segment):\n    return quote(segment, safe='')\n",
    ("safe=''", "safe='/'"),
    [c(["tenant/a"], "tenant%2Fa"), c(["a b"], "a%20b"), c(["x?y"], "x%3Fy")],
)
add(
    "case-insensitive-header",
    "http_api",
    "easy",
    "Look up a header in a list of name/value pairs case-insensitively, returning the last occurrence or null if absent.",
    "def solve(headers, name):\n    matches = [value for key,value in headers if key.lower()==name.lower()]\n    return matches[-1] if matches else None\n",
    ("key.lower()==name.lower()", "key==name"),
    [
        c([[["X-ID", "a"], ["x-id", "b"]], "X-Id"], "b"),
        c([[], "x"], None),
        c([[["Accept", "json"]], "accept"], "json"),
    ],
)
add(
    "bearer-scheme-parser",
    "http_api",
    "medium",
    "Extract a nonempty single-token Bearer credential with case-insensitive scheme and arbitrary surrounding/intervening whitespace; invalid headers return null.",
    "def solve(header):\n    parts = header.split()\n    return parts[1] if len(parts)==2 and parts[0].lower()=='bearer' else None\n",
    ("parts[0].lower()=='bearer'", "parts[0]=='Bearer'"),
    [
        c(["bearer abc"], "abc"),
        c([" Bearer\txyz "], "xyz"),
        c(["Bearer"], None),
        c(["Basic xyz"], None),
    ],
)
add(
    "json-content-type",
    "http_api",
    "medium",
    "Recognize application/json and application/*+json media types case-insensitively, ignoring parameters; reject text/json and unrelated application types.",
    "def solve(value):\n    media = value.split(';',1)[0].strip().lower()\n    return media == 'application/json' or (media.startswith('application/') and media.endswith('+json'))\n",
    ("value.split(';',1)[0].strip().lower()", "value.strip().lower()"),
    [
        c(["Application/JSON; charset=utf-8"], True),
        c(["application/problem+json"], True),
        c(["text/json"], False),
        c(["application/xml"], False),
    ],
)
add(
    "idempotent-retry-method",
    "http_api",
    "medium",
    "Allow safe retry for GET, HEAD, OPTIONS, PUT, DELETE, and for POST only with a nonempty idempotency key. Normalize method case.",
    "def solve(method, idempotency_key):\n    method = method.upper()\n    return method in {'GET','HEAD','OPTIONS','PUT','DELETE'} or (method=='POST' and bool(idempotency_key))\n",
    ("(method=='POST' and bool(idempotency_key))", "method=='POST'"),
    [
        c(["post", None], False),
        c(["POST", "key"], True),
        c(["get", None], True),
        c(["PATCH", "key"], False),
    ],
)
add(
    "bounded-attempt-count",
    "http_api",
    "easy",
    "An attempt can start only when prior attempts are below max_attempts and remaining time is strictly positive. max_attempts counts the initial attempt.",
    "def solve(attempts, max_attempts, remaining):\n    return 0 <= attempts < max_attempts and remaining > 0\n",
    ("attempts < max_attempts", "attempts <= max_attempts"),
    [c([3, 3, 10], False), c([0, 3, 1], True), c([0, 3, 0], False), c([-1, 3, 1], False)],
)
add(
    "pagination-next-offset",
    "http_api",
    "medium",
    "Return next offset only when returned_count equals positive page_size; an empty/short page ends pagination.",
    "def solve(offset, returned_count, page_size):\n    if page_size <= 0 or not 0 <= returned_count <= page_size: raise ValueError('page')\n    return offset + returned_count if returned_count == page_size else None\n",
    ("returned_count == page_size", "returned_count > 0"),
    [
        c([20, 3, 10], None),
        c([0, 10, 10], 10),
        c([0, 0, 10], None),
        c([0, 1, 0], raises="ValueError"),
    ],
)
add(
    "parse-next-link",
    "http_api",
    "hard",
    "Extract the URI with rel=next from an HTTP Link header. Relations may contain multiple space-separated tokens; absent next returns null.",
    "import re\ndef solve(header):\n    for uri, relations in re.findall(r'<([^>]+)>\\s*;\\s*rel=\"([^\"]+)\"', header):\n        if 'next' in relations.split(): return uri\n    return None\n",
    ("'next' in relations.split()", "relations == 'next'"),
    [
        c(['<https://e.test/2>; rel="next alternate"'], "https://e.test/2"),
        c(['<https://e.test/1>; rel="prev", <https://e.test/3>; rel="next"'], "https://e.test/3"),
        c(['<https://e.test/1>; rel="prev"'], None),
    ],
)

# Stateful maintenance examples use explicit action logs for reproducibility.
add(
    "idempotent-counter",
    "state",
    "medium",
    "Process [event_id, delta] pairs once per event id; the first occurrence wins even if a duplicate carries a different delta.",
    "def solve(events):\n    seen, total = set(), 0\n    for key, delta in events:\n        if key in seen: continue\n        seen.add(key)\n        total += delta\n    return total\n",
    ("if key in seen: continue", "if key in seen: pass"),
    [c([[["a", 2], ["a", 9], ["b", 3]]], 5), c([[]], 0), c([[["a", 0], ["a", 4]]], 0)],
)
add(
    "lru-access-refresh",
    "state",
    "hard",
    "Execute put/get actions in a positive-capacity LRU cache; get refreshes recency, missing get returns null, and return both get results and keys oldest-to-newest.",
    "from collections import OrderedDict\ndef solve(capacity, actions):\n    if capacity <= 0: raise ValueError('capacity')\n    cache, reads = OrderedDict(), []\n    for action in actions:\n        op,key,*rest = action\n        if op == 'put':\n            cache[key] = rest[0]\n            cache.move_to_end(key)\n            if len(cache)>capacity: cache.popitem(last=False)\n        else:\n            reads.append(cache.get(key))\n            if key in cache: cache.move_to_end(key)\n    return [reads,list(cache)]\n",
    ("if key in cache: cache.move_to_end(key)", "if key in cache: pass"),
    [
        c(
            [2, [["put", "a", 1], ["put", "b", 2], ["get", "a"], ["put", "c", 3], ["get", "b"]]],
            [[1, None], ["a", "c"]],
        ),
        c([1, [["get", "x"]]], [[None], []]),
        c([0, []], raises="ValueError"),
    ],
)
add(
    "expired-cache-read",
    "state",
    "medium",
    "Execute set(key,value,expiry) and get(key,now). Expiry is exclusive; an expired entry is deleted and returns null.",
    "def solve(actions):\n    cache, output = {}, []\n    for action in actions:\n        if action[0]=='set': cache[action[1]] = (action[2],action[3])\n        else:\n            _,key,now = action\n            if key in cache and cache[key][1] <= now: del cache[key]\n            output.append(cache[key][0] if key in cache else None)\n    return output\n",
    ("cache[key][1] <= now", "cache[key][1] < now"),
    [
        c([[["set", "a", 7, 10], ["get", "a", 10]]], [None]),
        c([[["set", "a", 0, 10], ["get", "a", 9]]], [0]),
        c([[["get", "x", 1]]], [None]),
    ],
)
add(
    "transaction-all-or-nothing",
    "state",
    "hard",
    "Apply account deltas atomically, rejecting the entire batch if any intermediate account balance would become negative. Return original balances on rejection.",
    "def solve(balances, changes):\n    working = balances.copy()\n    for account,delta in changes:\n        working[account] = working.get(account,0)+delta\n        if working[account]<0: return balances\n    return working\n",
    ("working = balances.copy()", "working = balances"),
    [
        c([{"a": 5, "b": 2}, [["a", -3], ["b", -4]]], {"a": 5, "b": 2}),
        c([{"a": 5}, [["a", -5]]], {"a": 0}),
        c([{}, [["a", 2]]], {"a": 2}),
    ],
)
add(
    "ledger-reversal-once",
    "state",
    "hard",
    "Sum charge events and reversal events referring to earlier charges; repeated reversal ids or attempts to reverse a charge twice must not subtract twice. Unknown charge reversals raise ValueError.",
    "def solve(events):\n    charges, reversed_ids, seen, total = {},set(),set(),0\n    for event in events:\n        if event['id'] in seen: continue\n        seen.add(event['id'])\n        if event['kind']=='charge':\n            charges[event['id']] = event['amount']\n            total += event['amount']\n        else:\n            target = event['target']\n            if target not in charges: raise ValueError('unknown charge')\n            if target not in reversed_ids:\n                total -= charges[target]\n                reversed_ids.add(target)\n    return total\n",
    ("if target not in reversed_ids:", "if target in charges:"),
    [
        c(
            [
                [
                    {"id": "c", "kind": "charge", "amount": 10},
                    {"id": "r1", "kind": "reverse", "target": "c"},
                    {"id": "r2", "kind": "reverse", "target": "c"},
                ]
            ],
            0,
        ),
        c([[{"id": "x", "kind": "reverse", "target": "z"}]], raises="ValueError"),
        c([[{"id": "a", "kind": "charge", "amount": 4}]], 4),
    ],
)
add(
    "optimistic-revision",
    "state",
    "medium",
    "Apply writes only when expected_revision equals the current revision, incrementing on each accepted write; return final state and booleans indicating accepted writes.",
    "def solve(value, revision, writes):\n    accepted = []\n    for expected,new_value in writes:\n        ok = expected == revision\n        accepted.append(ok)\n        if ok: value,revision = new_value,revision+1\n    return [value,revision,accepted]\n",
    ("expected == revision", "expected <= revision"),
    [
        c(["a", 1, [[1, "b"], [1, "c"]]], ["b", 2, [True, False]]),
        c(["a", 0, [[2, "z"]]], ["a", 0, [False]]),
        c([None, 0, []], [None, 0, []]),
    ],
)
add(
    "tenant-record-filter",
    "state",
    "medium",
    "Return only records belonging to the authenticated tenant and selected ids. Missing tenant fields must never grant access.",
    "def solve(records, tenant, ids):\n    return [row for row in records if row.get('tenant')==tenant and row.get('id') in ids]\n",
    (
        "row.get('tenant')==tenant and row.get('id') in ids",
        "row.get('tenant')==tenant or row.get('id') in ids",
    ),
    [
        c(
            [[{"tenant": "a", "id": 1}, {"tenant": "b", "id": 1}], "a", [1]],
            [{"tenant": "a", "id": 1}],
        ),
        c([[{"id": 1}], "a", [1]], []),
        c([[{"tenant": "a", "id": 1}], "a", []], []),
    ],
)
add(
    "outbox-lease-claim",
    "state",
    "hard",
    "Claim pending outbox items and processing items whose lease_until is at or before now; completed items are never claimable. Preserve order and honor positive limit.",
    "def solve(items,now,limit):\n    if limit<=0: raise ValueError('limit')\n    eligible = [x['id'] for x in items if x['state']=='pending' or (x['state']=='processing' and x['lease_until']<=now)]\n    return eligible[:limit]\n",
    ("x['lease_until']<=now", "x['lease_until']>=now"),
    [
        c(
            [
                [
                    {"id": "a", "state": "processing", "lease_until": 5},
                    {"id": "b", "state": "processing", "lease_until": 20},
                ],
                10,
                2,
            ],
            ["a"],
        ),
        c([[{"id": "x", "state": "done"}, {"id": "y", "state": "pending"}], 1, 1], ["y"]),
        c([[], 1, 0], raises="ValueError"),
    ],
)
add(
    "terminal-job-state",
    "state",
    "medium",
    "Apply a state transition only if allowed: queued->running/cancelled; running->succeeded/failed/cancelled. Terminal states reject every later transition.",
    "def solve(initial, transitions):\n    allowed = {'queued':{'running','cancelled'},'running':{'succeeded','failed','cancelled'}}\n    state, decisions = initial, []\n    for target in transitions:\n        ok = target in allowed.get(state,set())\n        decisions.append(ok)\n        if ok: state = target\n    return [state,decisions]\n",
    ("allowed.get(state,set())", "allowed.get(state,{'running'})"),
    [
        c(["cancelled", ["running"]], ["cancelled", [False]]),
        c(["queued", ["running", "succeeded", "running"]], ["succeeded", [True, True, False]]),
        c(["queued", ["succeeded"]], ["queued", [False]]),
    ],
)
add(
    "atomic-quota-reservations",
    "state",
    "hard",
    "Process nonnegative quota reservations sequentially; accepted amounts reduce remaining quota and denied amounts do not. Return decisions and remaining quota, rejecting negative input.",
    "def solve(quota, amounts):\n    if quota<0 or any(x<0 for x in amounts): raise ValueError('negative')\n    decisions = []\n    for amount in amounts:\n        ok = amount<=quota\n        decisions.append(ok)\n        if ok: quota-=amount\n    return [decisions,quota]\n",
    ("if ok: quota-=amount", "quota-=amount"),
    [
        c([5, [6, 5]], [[False, True], 0]),
        c([5, [2, 3, 1]], [[True, True, False], 0]),
        c([1, [-1]], raises="ValueError"),
    ],
)

# Serialization: stable wire forms and strict decoding.
add(
    "decimal-json-string",
    "serialization",
    "medium",
    "Serialize a decimal amount in a JSON object as its exact input decimal string, preserving trailing zeros; return parsed JSON-compatible data.",
    "import json\nfrom decimal import Decimal\ndef solve(text):\n    return json.loads(json.dumps({'amount':Decimal(text)}, default=str))\n",
    ("default=str", "default=float"),
    [
        c(["1.2300"], {"amount": "1.2300"}),
        c(["9007199254740993"], {"amount": "9007199254740993"}),
        c(["0"], {"amount": "0"}),
    ],
)
add(
    "datetime-wire-offset",
    "serialization",
    "medium",
    "Serialize an ISO datetime preserving its offset; naive input remains naive, and no timezone suffix may be fabricated.",
    "from datetime import datetime\ndef solve(value):\n    return datetime.fromisoformat(value).isoformat()\n",
    (
        "datetime.fromisoformat(value).isoformat()",
        "datetime.fromisoformat(value).replace(tzinfo=None).isoformat() + 'Z'",
    ),
    [
        c(["2026-01-01T07:00:00+07:00"], "2026-01-01T07:00:00+07:00"),
        c(["2026-01-01T00:00:00"], "2026-01-01T00:00:00"),
        c(["2026-01-01T00:00:00+00:00"], "2026-01-01T00:00:00+00:00"),
    ],
)
add(
    "base64url-padding",
    "serialization",
    "medium",
    "Decode a URL-safe Base64 UTF-8 string accepting omitted padding; invalid UTF-8 must raise UnicodeDecodeError.",
    "import base64\ndef solve(value):\n    padded = value + '=' * (-len(value)%4)\n    return base64.urlsafe_b64decode(padded).decode('utf-8')\n",
    ("value + '=' * (-len(value)%4)", "value"),
    [c(["aGk"], "hi"), c(["aGVsbG8="], "hello"), c(["_w"], raises="UnicodeDecodeError")],
)
add(
    "boolean-query-wire",
    "serialization",
    "easy",
    "Serialize a boolean query parameter as lowercase true or false; reject non-bool values.",
    "def solve(value):\n    if type(value) is not bool: raise TypeError('bool')\n    return 'true' if value else 'false'\n",
    ("'true' if value else 'false'", "str(value)"),
    [c([True], "true"), c([False], "false"), c([1], raises="TypeError")],
)
add(
    "csv-bom-header",
    "serialization",
    "medium",
    "Read CSV text into dictionaries, removing only an optional leading UTF-8 BOM before parsing headers.",
    "import csv\nimport io\ndef solve(value):\n    return list(csv.DictReader(io.StringIO(value.removeprefix('\\ufeff'))))\n",
    ("value.removeprefix('\\ufeff')", "value"),
    [
        c(["\ufeffid,name\n1,A\n"], [{"id": "1", "name": "A"}]),
        c(["id\n2\n"], [{"id": "2"}]),
        c([""], []),
    ],
)
add(
    "redact-url-credentials",
    "serialization",
    "hard",
    "Remove username/password from an HTTP URL while preserving host, explicit port, path, query and fragment, including bracketed IPv6 hosts.",
    "from urllib.parse import urlsplit,urlunsplit\ndef solve(url):\n    parsed = urlsplit(url)\n    netloc = parsed.netloc.rsplit('@',1)[-1]\n    return urlunsplit((parsed.scheme,netloc,parsed.path,parsed.query,parsed.fragment))\n",
    ("parsed.netloc.rsplit('@',1)[-1]", "parsed.hostname or ''"),
    [
        c(["https://user:pass@example.test:8443/a?q=1#x"], "https://example.test:8443/a?q=1#x"),
        c(["http://u:p@[::1]:80/"], "http://[::1]:80/"),
        c(["https://example.test/a"], "https://example.test/a"),
    ],
)
add(
    "canonical-json-order",
    "serialization",
    "medium",
    "Serialize JSON-compatible input with sorted object keys, compact separators, Unicode preserved, and NaN/infinity rejected.",
    "import json\ndef solve(value):\n    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)\n",
    ("sort_keys=True", "sort_keys=False"),
    [c([{"z": 1, "a": 2}], '{"a":2,"z":1}'), c([{"é": "x"}], '{"é":"x"}'), c([[1, 2]], "[1,2]")],
)
add(
    "ndjson-empty-lines",
    "serialization",
    "medium",
    "Parse nonblank JSON Lines independently; ignore whitespace-only lines and preserve zero, null, false, and empty objects.",
    "import json\ndef solve(text):\n    return [json.loads(line) for line in text.splitlines() if line.strip()]\n",
    ("if line.strip()", "if line"),
    [c(["0\n  \nnull\nfalse\n{}\n"], [0, None, False, {}]), c([""], []), c(["1\n2\n"], [1, 2])],
)
add(
    "schema-field-projection",
    "serialization",
    "easy",
    "Project an object to allowed fields, preserving present null/falsey values and omitting missing fields.",
    "def solve(payload, fields):\n    return {key:payload[key] for key in fields if key in payload}\n",
    ("if key in payload", "if payload.get(key)"),
    [
        c([{"a": 0, "b": None, "c": 3}, ["a", "b", "x"]], {"a": 0, "b": None}),
        c([{}, ["x"]], {}),
        c([{"a": False}, ["a"]], {"a": False}),
    ],
)
add(
    "strict-utf8-decoding",
    "serialization",
    "easy",
    "Decode a list of byte integers as UTF-8, raising UnicodeDecodeError for malformed encoding instead of silently dropping bytes.",
    "def solve(values):\n    return bytes(values).decode('utf-8', errors='strict')\n",
    ("errors='strict'", "errors='ignore'"),
    [c([[195, 169]], "é"), c([[255]], raises="UnicodeDecodeError"), c([[]], "")],
)

# Algorithms: interactions and boundary cases beyond one-line lookup examples.
add(
    "merge-touching-intervals",
    "algorithms",
    "medium",
    "Sort and merge closed intervals, merging touching endpoints as well as overlaps; reject reversed intervals.",
    "def solve(intervals):\n    result = []\n    for start,end in sorted(intervals):\n        if start>end: raise ValueError('interval')\n        if result and start<=result[-1][1]: result[-1][1]=max(result[-1][1],end)\n        else: result.append([start,end])\n    return result\n",
    ("start<=result[-1][1]", "start<result[-1][1]"),
    [
        c([[[1, 2], [2, 3], [5, 6]]], [[1, 3], [5, 6]]),
        c([[]], []),
        c([[[3, 1]]], raises="ValueError"),
    ],
)
add(
    "topological-cycle-detection",
    "algorithms",
    "hard",
    "Topologically order nodes 0..n-1 with edges [before,after], choosing the smallest currently available node; duplicate edges count once and cycles raise ValueError.",
    "import heapq\ndef solve(n,edges):\n    graph=[set() for _ in range(n)]\n    degree=[0]*n\n    for a,b in edges:\n        if b not in graph[a]: graph[a].add(b); degree[b]+=1\n    ready=[i for i in range(n) if degree[i]==0]\n    heapq.heapify(ready)\n    result=[]\n    while ready:\n        item=heapq.heappop(ready); result.append(item)\n        for nxt in sorted(graph[item]):\n            degree[nxt]-=1\n            if degree[nxt]==0: heapq.heappush(ready,nxt)\n    if len(result)!=n: raise ValueError('cycle')\n    return result\n",
    ("if len(result)!=n: raise ValueError('cycle')", "if len(result)>n: raise ValueError('cycle')"),
    [
        c([3, [[0, 1], [1, 0]]], raises="ValueError"),
        c([3, [[0, 2], [0, 2]]], [0, 1, 2]),
        c([0, []], []),
    ],
)
add(
    "first-equal-binary-search",
    "algorithms",
    "medium",
    "Return the first index equal to target in sorted values, or -1 when absent, including duplicate runs.",
    "from bisect import bisect_left\ndef solve(values,target):\n    pos=bisect_left(values,target)\n    return pos if pos<len(values) and values[pos]==target else -1\n",
    ("from bisect import bisect_left", "from bisect import bisect_right as bisect_left"),
    [c([[1, 2, 2, 3], 2], 1), c([[1, 3], 2], -1), c([[], 1], -1)],
)
add(
    "ragged-matrix-transpose",
    "algorithms",
    "medium",
    "Transpose ragged rows, padding missing entries with null through the longest row; an empty matrix or all-empty rows yields an empty list.",
    "from itertools import zip_longest\ndef solve(rows):\n    return [list(column) for column in zip_longest(*rows,fillvalue=None)]\n",
    ("zip_longest(*rows,fillvalue=None)", "zip(*rows)"),
    [c([[[1, 2], [3]]], [[1, 3], [2, None]]), c([[]], []), c([[[], []]], [])],
)
add(
    "stable-top-k",
    "algorithms",
    "medium",
    "Select the first k records by descending score, keeping original order on tied scores; reject negative k and return none for k=0.",
    "def solve(records,k):\n    if k<0: raise ValueError('k')\n    return sorted(records,key=lambda row:-row['score'])[:k]\n",
    ("key=lambda row:-row['score']", "key=lambda row:(-row['score'],row['id'])"),
    [
        c(
            [[{"id": "b", "score": 5}, {"id": "a", "score": 5}, {"id": "c", "score": 1}], 2],
            [{"id": "b", "score": 5}, {"id": "a", "score": 5}],
        ),
        c([[{"id": "a", "score": 1}], 0], []),
        c([[], -1], raises="ValueError"),
    ],
)
add(
    "bounded-shortest-path",
    "algorithms",
    "hard",
    "Return shortest edge count from start to goal within max_depth in an adjacency dictionary. Cycles must terminate and start==goal has distance zero.",
    "from collections import deque\ndef solve(graph,start,goal,max_depth):\n    queue=deque([(start,0)]); seen={start}\n    while queue:\n        node,depth=queue.popleft()\n        if node==goal: return depth\n        if depth>=max_depth: continue\n        for nxt in graph.get(node,[]):\n            if nxt not in seen: seen.add(nxt); queue.append((nxt,depth+1))\n    return None\n",
    ("if depth>=max_depth: continue", "if depth>max_depth: continue"),
    [
        c([{"a": ["b"], "b": ["c"]}, "a", "c", 1], None),
        c([{"a": ["b"], "b": ["a", "c"]}, "a", "c", 2], 2),
        c([{}, "a", "a", 0], 0),
    ],
)
add(
    "coalesce-adjacent-integers",
    "algorithms",
    "medium",
    "Convert unsorted integer values to inclusive consecutive ranges, removing duplicates.",
    "def solve(values):\n    result=[]\n    for value in sorted(set(values)):\n        if result and value==result[-1][1]+1: result[-1][1]=value\n        else: result.append([value,value])\n    return result\n",
    ("sorted(set(values))", "sorted(values)"),
    [c([[3, 1, 2, 2, 5]], [[1, 3], [5, 5]]), c([[]], []), c([[-2, -1, 1]], [[-2, -1], [1, 1]])],
)
add(
    "insert-after-equals",
    "algorithms",
    "easy",
    "Insert a new numeric value into a sorted list after existing equal values and return its insertion index alongside the new list.",
    "from bisect import bisect_right\ndef solve(values,value):\n    pos=bisect_right(values,value)\n    return [pos,values[:pos]+[value]+values[pos:]]\n",
    ("from bisect import bisect_right", "from bisect import bisect_left as bisect_right"),
    [c([[1, 2, 2, 3], 2], [3, [1, 2, 2, 2, 3]]), c([[], 1], [0, [1]]), c([[2], 1], [0, [1, 2]])],
)
add(
    "retry-status-machine",
    "algorithms",
    "hard",
    "Consume statuses in order until first success, permanent failure, or max_attempts; retry only transient. Return attempt count and final state; max_attempts must be positive.",
    "def solve(statuses,max_attempts):\n    if max_attempts<=0: raise ValueError('attempts')\n    count=0; state='exhausted'\n    for status in statuses[:max_attempts]:\n        count+=1\n        if status=='success': state='succeeded'; break\n        if status=='permanent': state='failed'; break\n    return [count,state]\n",
    ("if status=='permanent': state='failed'; break", "if status=='permanent': state='failed'"),
    [
        c([["permanent", "success"], 3], [1, "failed"]),
        c([["transient", "success", "success"], 3], [2, "succeeded"]),
        c([["transient", "transient"], 1], [1, "exhausted"]),
        c([[], 0], raises="ValueError"),
    ],
)
add(
    "exponential-moving-average",
    "algorithms",
    "medium",
    "Compute an exponential moving average initialized from the first sample, with alpha in [0,1]; return all intermediate values and an empty list for no data.",
    "def solve(values,alpha):\n    if not 0<=alpha<=1: raise ValueError('alpha')\n    if not values: return []\n    average=values[0]; out=[average]\n    for value in values[1:]:\n        average=alpha*value+(1-alpha)*average\n        out.append(average)\n    return out\n",
    ("average=values[0]; out=[average]", "average=0; out=[average]"),
    [
        c([[10, 20, 30], 0.5], [10, 15, 22.5]),
        c([[4, 9], 0], [4, 4]),
        c([[], 1], []),
        c([[1], 2], raises="ValueError"),
    ],
)

# Authorization/security decisions are tested as policies, not sandbox claims.
add(
    "upload-basename-validation",
    "security_logic",
    "medium",
    "Accept nonempty upload basenames, rejecting dot/dotdot, NUL, slash and backslash. A hidden file such as .env is allowed by this basename-only policy.",
    "def solve(name):\n    return bool(name) and name not in {'.','..'} and not any(x in name for x in ('/','\\\\','\\0'))\n",
    ("('/','\\\\','\\0')", "('/','\\0')"),
    [c(["file.txt"], True), c(["..\\secret"], False), c(["../secret"], False), c([".env"], True)],
)
add(
    "exact-allowed-host",
    "security_logic",
    "hard",
    "Authorize an HTTPS URL only if its parsed hostname exactly matches an allowlisted host case-insensitively; userinfo, subdomain suffixes, and fragments cannot confer access.",
    "from urllib.parse import urlsplit\ndef solve(url,allowed):\n    parsed=urlsplit(url)\n    return parsed.scheme=='https' and parsed.hostname is not None and parsed.hostname.lower() in {x.lower() for x in allowed}\n",
    (
        "parsed.hostname.lower() in {x.lower() for x in allowed}",
        "any(x.lower() in parsed.netloc.lower() for x in allowed)",
    ),
    [
        c(["https://good.test.evil.test/", ["good.test"]], False),
        c(["https://good.test@evil.test/", ["good.test"]], False),
        c(["https://GOOD.test/a", ["good.test"]], True),
        c(["http://good.test/", ["good.test"]], False),
    ],
)
add(
    "html-attribute-escaping",
    "security_logic",
    "easy",
    "Escape HTML text including both quote types so the output can safely occupy a quoted attribute.",
    "import html\ndef solve(value):\n    return html.escape(value,quote=True)\n",
    ("quote=True", "quote=False"),
    [
        c(['" onclick="x'], "&quot; onclick=&quot;x"),
        c(["<b>&'"], "&lt;b&gt;&amp;&#x27;"),
        c(["safe"], "safe"),
    ],
)
add(
    "recursive-secret-redaction",
    "security_logic",
    "hard",
    "Recursively replace values under password, token, or api_key keys, case-insensitively, with [REDACTED] while retaining dictionary/list structure.",
    "def solve(value):\n    if isinstance(value,dict):\n        return {k:'[REDACTED]' if k.lower() in {'password','token','api_key'} else solve(v) for k,v in value.items()}\n    if isinstance(value,list): return [solve(v) for v in value]\n    return value\n",
    (
        "if isinstance(value,list): return [solve(v) for v in value]",
        "if isinstance(value,list): return value",
    ),
    [
        c(
            [{"items": [{"TOKEN": "x", "name": "a"}]}],
            {"items": [{"TOKEN": "[REDACTED]", "name": "a"}]},
        ),
        c([{"password": "p"}], {"password": "[REDACTED]"}),
        c(["x"], "x"),
    ],
)
add(
    "tenant-cache-key-collision",
    "security_logic",
    "medium",
    "Build an unambiguous cache key from tenant, resource, and revision using a compact JSON array; components may contain colons or separators.",
    "import json\ndef solve(tenant,resource,revision):\n    return json.dumps([tenant,resource,revision],separators=(',',':'),ensure_ascii=False)\n",
    (
        "json.dumps([tenant,resource,revision],separators=(',',':'),ensure_ascii=False)",
        "f'{tenant}:{resource}:{revision}'",
    ),
    [
        c(["a:b", "c", 1], '["a:b","c",1]'),
        c(["a", "b:c", 1], '["a","b:c",1]'),
        c(["", "x", 0], '["","x",0]'),
    ],
)
add(
    "all-required-scopes",
    "security_logic",
    "easy",
    "Authorize only when every required scope is present in granted scopes. An empty required set is allowed.",
    "def solve(granted,required):\n    return set(required).issubset(set(granted))\n",
    ("set(required).issubset(set(granted))", "bool(set(required)&set(granted))"),
    [
        c([["read"], ["read", "write"]], False),
        c([["read", "write"], ["write"]], True),
        c([[], []], True),
    ],
)
add(
    "overlapping-redaction-spans",
    "security_logic",
    "hard",
    "Replace the union of overlapping or touching half-open spans with one [REDACTED] marker per merged span; validate span bounds and ignore empty spans.",
    "def solve(text,spans):\n    merged=[]\n    for start,end in sorted(spans):\n        if not 0<=start<=end<=len(text): raise ValueError('span')\n        if start==end: continue\n        if merged and start<=merged[-1][1]: merged[-1][1]=max(end,merged[-1][1])\n        else: merged.append([start,end])\n    out=[]; pos=0\n    for start,end in merged: out.extend([text[pos:start],'[REDACTED]']); pos=end\n    out.append(text[pos:])\n    return ''.join(out)\n",
    ("pos=end\n", "pos=start\n"),
    [
        c(["abcdefgh", [[1, 4], [3, 6]]], "a[REDACTED]gh"),
        c(["abc", [[0, 0]]], "abc"),
        c(["abc", [[0, 4]]], raises="ValueError"),
    ],
)
add(
    "approval-expiry-and-version",
    "security_logic",
    "hard",
    "An approved action may execute only for the bound tenant, unchanged revision, strictly before expires_at, and while not already consumed.",
    "def solve(approval,tenant,revision,now):\n    return approval['decision']=='approved' and approval['tenant']==tenant and approval['revision']==revision and now<approval['expires_at'] and not approval['consumed']\n",
    ("approval['revision']==revision", "approval['revision']<=revision"),
    [
        c(
            [
                {
                    "decision": "approved",
                    "tenant": "a",
                    "revision": 1,
                    "expires_at": 10,
                    "consumed": False,
                },
                "a",
                2,
                5,
            ],
            False,
        ),
        c(
            [
                {
                    "decision": "approved",
                    "tenant": "a",
                    "revision": 1,
                    "expires_at": 10,
                    "consumed": False,
                },
                "a",
                1,
                5,
            ],
            True,
        ),
        c(
            [
                {
                    "decision": "approved",
                    "tenant": "a",
                    "revision": 1,
                    "expires_at": 10,
                    "consumed": False,
                },
                "a",
                1,
                10,
            ],
            False,
        ),
    ],
)
add(
    "canonical-signature-input",
    "security_logic",
    "medium",
    "Return SHA-256 of the UTF-8 canonical JSON encoding of a payload using sorted keys, compact separators, and Unicode preserved. This is an integrity fingerprint, not authentication.",
    "import hashlib\nimport json\ndef solve(payload):\n    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')\n    return hashlib.sha256(encoded).hexdigest()\n",
    ("sort_keys=True", "sort_keys=False"),
    [
        c([{"b": 2, "a": 1}], hashlib.sha256(b'{"a":1,"b":2}').hexdigest()),
        c([{}], hashlib.sha256(b"{}").hexdigest()),
        c([{"é": 1}], hashlib.sha256('{"é":1}'.encode()).hexdigest()),
    ],
)
add(
    "relative-path-containment",
    "security_logic",
    "hard",
    "Normalize a POSIX relative path without touching the filesystem. Reject absolute paths and any dotdot component that would escape the base; allow in-base dotdot normalization.",
    "def solve(path):\n    if path.startswith('/'): raise ValueError('absolute')\n    parts=[]\n    for part in path.split('/'):\n        if part in ('','.'): continue\n        if part=='..':\n            if not parts: raise ValueError('escape')\n            parts.pop()\n        else: parts.append(part)\n    return '/'.join(parts)\n",
    ("if not parts: raise ValueError('escape')", "if not parts: continue"),
    [
        c(["../secret"], raises="ValueError"),
        c(["a/../b"], "b"),
        c(["/x"], raises="ValueError"),
        c(["a/./b"], "a/b"),
    ],
)


def build():
    if len(TASKS) != 100:
        raise ValueError(f"Expected exactly 100 version-one tasks, got {len(TASKS)}")
    path = Path(__file__).parent / "data/tasks-v1.jsonl"
    # Mapping insertion order is observable for a few API contracts; do not sort
    # nested case argument dictionaries while writing this deterministic corpus.
    payload = "".join(
        json.dumps(task, ensure_ascii=False, separators=(",", ":")) + "\n" for task in TASKS
    ).encode()
    path.write_bytes(payload)
    print(
        json.dumps(
            {"tasks": len(TASKS), "sha256": hashlib.sha256(payload).hexdigest(), "path": str(path)}
        )
    )


if __name__ == "__main__":
    build()
