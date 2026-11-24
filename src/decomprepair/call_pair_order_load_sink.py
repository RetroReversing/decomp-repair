"""A call that reads a point put back after the call that writes it, and loads sunk past a call to their use.

m2c and searches leave two kinds of drift in long runs of calls such as `segmentClosestPoint(out, a, b, p); d =
distanceSquared3D(out, p);` repeated per triangle edge:

- a reader moved above its writer: `d = dist(q, p); seg(q, ..);` where the same function elsewhere writes
  `seg(q, ..); d = dist(q, ..);`. The swap restores the program's order (the reader saw a stale point before).
- a plain load (`v = rec->verts;`) computed before a call and first read after it: crossing the call it needs a saved
  register; the target loads it again right before its use (`lw $v1, 0x34($s2)` beside each call). The child sinks it.

A 1928-instruction collision sweep (KMC gcc 2.7.2): sinking alone 13774 -> 13279, one swap alone worse (15853), both
12963; a second swap made it worse again (the judge picks). Children: all sinks; all sinks with each swap; all sinks
with every swap; then each sink and each swap alone.
"""
import re

from .csource import _blank, find

FAMILY = 'call_pair_order_load_sink'
COMBINED = 'call_pair_order_load_sink_all'
FAMILIES = (FAMILY, COMBINED)

I = r'[A-Za-z_]\w*'
CALL = re.compile(r'^[ \t]*(?:(?P<res>' + I + r')\s*=\s*)?(?P<f>' + I + r')\s*\(\s*(?:\(\s*\w+\s*\*\s*\)\s*)?(?P<a>' + I +
                  r')\s*[,)].*;\s*$')
LOAD = re.compile(r'^[ \t]*(?P<v>' + I + r')\s*=\s*(?P<e>[^;(]*\([^;]*\)[^;]*|[^;]*);\s*$')


def _call(line):
    m = CALL.match(line)
    return (m['f'], m['a'], m['res']) if m else None


def _orders(lines):
    """(writer, reader) callee pairs seen as `writer(p, ..);` directly followed by `.. reader(p, ..);`."""
    seen = set()
    for x, y in zip(lines, lines[1:]):
        a, b = _call(x), _call(y)
        if a and b and a[1] == b[1] and a[0] != b[0] and not a[2]:
            seen.add((a[0], b[0]))
    return seen


def _swaps(lines):
    orders = _orders(lines)
    out = []
    for i in range(len(lines) - 1):
        a, b = _call(lines[i]), _call(lines[i + 1])
        if a and b and a[1] == b[1] and (b[0], a[0]) in orders and a[2] and not b[2]:
            out.append(i)
    return out


def _sinks(lines):
    """(i, j): line i is a call-free load whose variable is first read on line j, after a call line between."""
    out = []
    for i, line in enumerate(lines):
        m = LOAD.match(line)
        if not m or re.search(I + r'\s*\(', re.sub(r'\(\s*\w+\s*\*\s*\)', '', m['e'])):
            continue
        v = m['v']
        if re.search(r'\b' + v + r'\b', m['e']):
            continue
        crossed = False
        for j in range(i + 1, min(i + 12, len(lines))):
            if re.search(r'[{}]', lines[j]):
                break
            if re.search(r'\b' + v + r'\b', lines[j]):
                if crossed and not re.match(r'\s*' + v + r'\s*=(?!=)', lines[j]):
                    out.append((i, j))
                break
            if _call(lines[j]):
                crossed = True
            elif any(re.search(r'\b' + w + r'\b', lines[j]) for w in re.findall(I, m['e'])
                     if re.match(r'\s*' + w + r'\s*=(?!=)', lines[j])):
                break  # an operand of the load is set in between
    return out


def _apply(lines, swaps, sinks):
    lines = list(lines)
    for i in swaps:
        lines[i], lines[i + 1] = lines[i + 1], lines[i]
    moved = sorted(sinks, key=lambda s: s[0], reverse=True)
    for i, j in moved:
        line = lines.pop(i)
        lines.insert(j - 1, line)
    return lines


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    lines = source[opening:span[1]].split('\n')
    swaps, sinks = _swaps(lines), _sinks(lines)
    # line numbers shift under a swap inside a sink's span: keep the sinks clear of every swap
    sinks = [s for s in sinks if not any(s[0] <= i + 1 and i <= s[1] for i in swaps)]
    wrap = lambda ls: source[:opening] + '\n'.join(ls) + source[span[1]:]  # noqa: E731
    out = []
    if sinks:
        out.append((COMBINED, wrap(_apply(lines, [], sinks))))
        out += [(COMBINED, wrap(_apply(lines, [i], sinks))) for i in swaps]
    if swaps and (len(swaps) > 1 or not sinks):
        out.append((COMBINED, wrap(_apply(lines, swaps, sinks))))
    out += [(FAMILY, wrap(_apply(lines, [], [s]))) for s in sinks[:6]]
    out += [(FAMILY, wrap(_apply(lines, [i], []))) for i in swaps[:6]]
    return out[:16]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
