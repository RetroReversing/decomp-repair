"""A pointer local built from a sum, and a later sum of the same two values that must stay a separate add.

`P = (T *)(A + B);` followed by loads through `P`, then in a later statement `A + (B + K)` or `A + B + K` (the same
two registers and an offset, a record's member address): cse finds `A + B` already held by `P` and writes the later
address as `P + K`. The target's compiler did not: it adds `B` and `A` again beside the call (`addu $a1,$s1,$a2;
addiu $a1,$a1,K`), so `A` stays live to that add and the registers around it differ from the ones the shared sum
gives. Two things are needed together and each alone is worse or neutral:

- The later sum written `B + A + K` (the sum first, the offset last). Written `A + (B + K)` GCC 2.7.2 folds the offset
  into `A` first (`addiu a1,a1,K` then `addu`), which makes `A` the first operand of an insn whose result local-alloc
  has already put in an argument register, and global.c's `set_preference` then gives `A` that register as a
  preference: `A` takes `$a1` and the 0xFF compare constant, which should hold `$a1`, ends in `$a2`.
- `P` assigned again before that statement (`P = 0;`, a store flow deletes). cse invalidates `P`'s equivalence, finds
  no register that holds `A + B` and leaves the add where the source wrote it. With the sum written `B + A + K` and
  `P` not reassigned the add is shared again (`addiu $a1,$v0,K`, `A` dead early) and `B`'s saved register loses a
  reference: every saved register shifts (480).

The case (KMC GCC 2.7.2, `-O2 -G0 -mips3`): a 218-instruction object-matrix function indexing 0xD4-byte records,
`parent = (R *)(records + temp_s1)` read three times, then the argument `(u32)records + (u32)(temp_s1 + 0x9C)` of a call
in the arm of `if (parent->parent == 0xFF)`. Saved best 220 (records in `$a1`, the constant in `$a2`); the sum
rewritten alone 480, the reassignment alone 220 (the sum was not shared yet); both 120, the rest of the rows being
the order of a global's load (`global_base_before_index`). The compiler-source reading (cse.c's equivalences,
global.c's `expand_preferences` and `set_preference`) is a hypothesis the measurement agrees with; the judge decides
each child. The reassignment is a dead store, scaffolding a faithful source would not have: the child is a
hypothesis about what the game's source did to stop cse (`P` reused for another record, say).

The child (`pointer_sum_cse_barrier`, one per pair, bounded) rewrites the later sum and inserts `P = 0;` before its
statement when:
- `P = A + B;` (a cast and parentheses allowed) assigns two plain locals, and `P` is read at least once after it;
- a later statement holds `A + (B + K)`, `(B + K) + A`, `A + B + K` or `B + A + K` (`K` a number, casts allowed) and
  does not mention `P`; a form already written `B + A + K` or `A + B + K` gets only the reassignment;
- `P` is not mentioned after that statement, and the statement is not an `else` branch's own head.
"""
import re

from .csource import _blank, find
from .reassigned_local_inline import IDENT

FAMILY = 'pointer_sum_cse_barrier'
FAMILIES = (FAMILY,)
LIMIT = 6
NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
CAST = r'\(\s*(?:unsigned\s+|signed\s+)?[A-Za-z_][\w\s]*?\s*\**\s*\)'
DEF_CAST = re.compile(rf'(?<![\w.>])(?P<p>{IDENT})\s*=(?!=)\s*(?:{CAST}\s*)?\(\s*(?P<a>{IDENT})\s*\+\s*(?P<b>{IDENT})\s*\)\s*;')
DEF_PLAIN = re.compile(rf'(?<![\w.>])(?P<p>{IDENT})\s*=(?!=)\s*(?:{CAST}\s*)?(?P<a>{IDENT})\s*\+\s*(?P<b>{IDENT})\s*;')


def _uses(a, b):
    """The later-sum shapes for `a` and `b`: (regex, whether it needs the sum rewritten first)."""
    ca, cb = rf'(?P<c1>{CAST}\s*)?', rf'(?P<c2>{CAST}\s*)?'
    return [
        (re.compile(rf'(?<![\w.>]){ca}\b{a}\b\s*\+\s*{cb}\(\s*\b{b}\b\s*\+\s*(?P<k>{NUMBER})\s*\)'), True),
        (re.compile(rf'{cb}\(\s*\b{b}\b\s*\+\s*(?P<k>{NUMBER})\s*\)\s*\+\s*{ca}\b{a}\b'), True),
        (re.compile(rf'(?<![\w.>]){ca}\b{a}\b\s*\+\s*(?:{CAST}\s*)?\b{b}\b\s*\+\s*(?P<k>{NUMBER})\b'), False),
        (re.compile(rf'(?<![\w.>]){ca}\b{b}\b\s*\+\s*(?:{CAST}\s*)?\b{a}\b\s*\+\s*(?P<k>{NUMBER})\b'), False),
    ]


def variants(source, name):
    clean = _blank(source)
    span = find(source, name)
    if not span:
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    result = []
    seen = set()
    for pattern in (DEF_CAST, DEF_PLAIN):
        for definition in pattern.finditer(clean, opening, end):
            p, a, b = definition['p'], definition['a'], definition['b']
            if p in (a, b) or (p, a, b) in seen:
                continue
            seen.add((p, a, b))
            mention = re.compile(rf'(?<![\w.>]){re.escape(p)}\b')
            for shape, rewrite in _uses(re.escape(a), re.escape(b)):
                for use in shape.finditer(clean, definition.end(), end):
                    head = max(clean.rfind(';', 0, use.start()), clean.rfind('{', 0, use.start()),
                               clean.rfind('}', 0, use.start())) + 1
                    stop = clean.find(';', use.end())
                    if stop < 0 or head <= definition.end() - 1:
                        continue
                    if re.match(r'\s*(?:else|for|while|do|switch|case|default)\b', clean[head:use.start()]):
                        continue
                    if mention.search(clean, head, stop) or mention.search(clean, head, end):
                        continue
                    if not mention.search(clean, definition.end(), head):
                        continue
                    indent = re.match(r'\s*', source[head:]).group()
                    first = head + len(indent)
                    new = source[use.start():use.end()]
                    if rewrite:
                        cast = (use['c1'] or use['c2'] or '').strip()
                        if cast and cast[0] == '(':
                            cast = cast.replace(' ', '')
                        new = f'{cast}{b} + {cast}{a} + {use["k"]}'
                    text = (source[:first] + f'{p} = 0; ' + source[first:use.start()] + new + source[use.end():])
                    if text != source and text not in result:
                        result.append(text)
    return [(FAMILY, text) for text in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)
