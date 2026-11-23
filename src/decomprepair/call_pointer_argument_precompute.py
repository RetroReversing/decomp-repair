"""A call's `base + offset` pointer argument computed before the `if` that sets another of its arguments.

m2c writes `if (!(f > 0.0f)) { var_a2 = 0; } play(arg0 + 0x24, 1, var_a2);`: the address is computed after the branch, into the
first argument register, and the branch's two paths each need their own `move`/`addiu`. The target computes it first
(`addiu $a0, $s2, 0x24` fills the delay slot of the compare's `bc1t`, then `move $a2, $zero`, then the call): the game's
source held the address in a local before the test. A KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) player-update
routine of 1137 instructions went 2321 -> 1420 with the local at two such calls (one step of a chain that ended 60 from
a match: the first half of the gain came from the `bc1fl` with `move $a2, $zero` in its slot turning into `bc1t` with the
address in the slot).

call_pointer_argument_precompute
    A call statement `f(P + K, ...);` (P a `void *` parameter or local, K a literal, no other call in the argument) right
    after a braced `if (...) { ... }` that does not mention P and has no `else`: one child declares `P_plus_K` as `void *`,
    writes `P_plus_K = P + K;` before that `if` and passes it. One child per call, at most 6; the calls of one function are
    offered one at a time and in the one child that holds all of them (the target needed both)."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT

FAMILY = 'call_pointer_argument_precompute'
FAMILIES = (FAMILY,)
LIMIT = 6
_CALL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<fn>{IDENT})\s*\(\s*(?P<base>{IDENT})\s*\+\s*(?P<off>0[xX][0-9A-Fa-f]+|\d+)\s*(?P<rest>(?:,[^;{{}}]*)?)\)\s*;')


def _pointer(clean, base):
    return bool(re.search(rf'\bvoid\s*\*\s*{re.escape(base)}\b', clean))


def _apply(source, hits):
    text = source
    for hit, if_at, name in sorted(hits, key=lambda h: h[0].start(), reverse=True):
        start, end = hit.start(), hit.end()
        call = f'{hit["indent"]}{hit["fn"]}({name}{hit["rest"]});'
        text = text[:start] + call + text[end:]
        line = text.rfind('\n', 0, if_at) + 1
        text = text[:line] + f'{hit["indent"]}{name} = {hit["base"]} + {hit["off"]};\n' + text[line:]
    return text


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    found = []
    for hit in _CALL.finditer(clean, opening, span[1]):
        if not _pointer(clean[opening - 400 if opening > 400 else 0:span[1]], hit['base']) or re.search(rf'{IDENT}\s*\(', hit['rest']):
            continue
        before = clean[opening:hit.start()].rstrip()
        if not before.endswith('}'):
            continue
        depth, at = 0, len(before) - 1
        for pos in range(len(before) - 1, -1, -1):
            depth += 1 if before[pos] == '}' else -1 if before[pos] == '{' else 0
            if depth == 0:
                at = pos
                break
        head = before[:at].rstrip()
        branch = re.search(r'\bif\s*\([^{};]*\)\s*$', head) or re.search(r'\bif\s*\((?:[^{};]|\([^{}]*\))*\)\s*$', head)
        if not branch:
            continue
        body = before[at:]
        if re.search(rf'\b{re.escape(hit["base"])}\b', body) or re.match(r'\s*else\b', clean[hit.start() - 5:hit.start()]):
            continue
        if_at = opening + branch.start()
        found.append((hit, if_at, f'{hit["base"]}_plus_{int(hit["off"], 0):X}'))
    out = []
    for item in found:
        text = _apply(source, [item])
        out.append(text)
    if len(found) > 1:
        out.append(_apply(source, found))
    declared = []
    for text in out:
        names = sorted({n for _, _, n in found if f'{n} =' in text})
        body = text.find('\n', text.find('{', span[0])) + 1
        indent = re.match(r'[ \t]*', text[body:])[0] or '  '
        declared.append(text[:body] + ''.join(f'{indent}void *{n};\n' for n in names) + text[body:])
    return [(FAMILY, text) for text in dict.fromkeys(declared)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
