"""A byte copy of a word kept in a local, read where the word is masked again, and set again where it cannot change.

`v = (u8) x;` is a move into a byte-mode pseudo: no instruction, and each later use extends it (`andi $v0, $s3, 0xff`).
That register is the one the target keeps for a byte that outlives a call, in a register of its own beside the word's.
A draft chain leaves the copy half used: the later stores read `x & 0xFF` (cse folds them back onto the word, so the
copy's register has fewer uses than the target's and moves in the allocation order), and `v = x & 0xFF;` is written
again after a call and before a test of it, which makes `v` a pseudo with two sets that no longer behaves as a copy.
On a 313-instruction display-list loop (KMC GCC 2.7.2, `-O2 -G0 -mips3`) the three edits together took a source from 2185
(its chain stopped at 100) to a chain that reaches 0: the stores read `v`, the reassignments go, and the test reads the
word's own low byte.

`variants` takes a local `u8`/`unsigned char` (`v`) set once to `(u8) x` for a plain local or parameter `x` that is
assigned at most once, and offers every non-empty combination of three edits that apply: drop the `v = x & 0xFF;`
reassignments (also written `(u32) x & 0xFF`), write `if (v)` / `if (!v)` as the test of `x & 0xFF`, and write each
parenthesised `(x & 0xFF)` outside a test as `v`. At most 7 proposals. Each is a hypothesis; the judge decides."""
import itertools
import re

from .csource import find

FAMILY = 'narrow_copy_reuse'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_BYTE = r'(?:u8|unsigned\s+char)'
_FIRST = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<v>{_ID})[ \t]*=[ \t]*\([ \t]*{_BYTE}[ \t]*\)[ \t]*(?P<x>{_ID})[ \t]*;[ \t]*$')


def _reassign(v, x):
    cast = r'\([ \t]*(?:u32|unsigned(?:[ \t]+int)?)[ \t]*\)[ \t]*'
    return re.compile(rf'(?m)^[ \t]*{re.escape(v)}[ \t]*=[ \t]*\(?[ \t]*(?:{cast})?{re.escape(x)}[ \t]*\)?[ \t]*&[ \t]*0[xX][fF][fF][ \t]*;[ \t]*\n')


def _is_group(before):
    """Whether a `(` after `before` opens a parenthesised expression: not a call's, an `if`'s or a `while`'s parenthesis
    (after a cast, an operator, `return` or another `(` it does)."""
    before = before.rstrip()
    if not before:
        return True
    if before[-1] == ']':
        return False
    word = re.search(r'[A-Za-z_]\w*$', before)
    return not word or word[0] == 'return'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    out = []
    for first in _FIRST.finditer(text):
        v, x = first['v'], first['x']
        if not re.search(rf'\b{_BYTE}[ \t]+{re.escape(v)}\s*;', text) or v == x:
            continue
        if len(re.findall(rf'\b{re.escape(x)}\s*=[^=]', text)) > 1 or re.search(rf'&\s*{re.escape(x)}\b(?!\s*0)', text.replace(f'{x} & 0xFF', '')):
            continue
        again = list(_reassign(v, x).finditer(text))
        guard = re.compile(rf'\bif\s*\(\s*(?P<not>!?)\s*{re.escape(v)}\s*\)')
        guards = list(guard.finditer(text))
        use = re.compile(rf'(?<!\bif)(?<!\bif )\(\s*{re.escape(x)}\s*&\s*0[xX][fF][fF]\s*\)')
        uses = [hit for hit in use.finditer(text) if _is_group(text[:hit.start()])]
        kinds = [kind for kind, hits in (('drop', again), ('guard', guards), ('use', uses)) if hits]
        for size in range(1, len(kinds) + 1):
            for chosen in itertools.combinations(kinds, size):
                edits = []
                if 'drop' in chosen:
                    edits += [(hit.start(), hit.end(), '') for hit in again if hit.start() > first.end()]
                if 'guard' in chosen:
                    edits += [(hit.start(), hit.end(), f"if ({hit['not']}({x} & 0xFF))") for hit in guards]
                if 'use' in chosen:
                    edits += [(hit.start(), hit.end(), v) for hit in uses]
                if not edits:
                    continue
                child = text
                for start, end, new in sorted(edits, reverse=True):
                    child = child[:start] + new + child[end:]
                out.append((FAMILY, source[:span[0]] + child + source[span[1]:]))
    return list(dict.fromkeys(out))[:7]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 99}  # the registry: no caller wiring (registry.py)
