"""A constant local that only feeds `==`/`!=` compares, written as its literal again.

`sentinel_constant_local` gives a sentinel literal a local of its own; that helps when GCC 2.7.2 should keep the
constant in a register. The reverse was missing. On a 1928-instruction collision sweep (KMC GCC 2.7.2, `-G0 -mips3
-mgp32 -mfp32 -O2`) a search had left `s32 sentinel = -1;` at the top for one `if (hit != sentinel)` after the object
loop. The local lived over the whole function and was spilled, so the compare read two stack slots and reload needed a
second register (`$t5`) for it, which moved every later spill; the target loads `li $v0, -1` next to the compare. The
literal back: 1467 -> 487, every `$t5` row gone.

sentinel_local_inline
    `T v = K;` (or `T v; .. v = K;` once), `v` never assigned again, never address-taken, read only as an operand of
    `==` or `!=`: every read written `K` (negative literals parenthesised) and the local removed. One child per local.

Hypothesis from the match: a constant read once and far away from its set is a long-lived pseudo the allocator may
spill; the literal is materialised beside its use. The exact judge decides.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'sentinel_local_inline'
FAMILIES = (FAMILY,)
LIMIT = 6
_INT = r'(?:register\s+)?(?:u8|s8|u16|s16|u32|s32|int|short|long|unsigned(?:\s+(?:int|short|long))?|signed(?:\s+int)?)'
_LITERAL = r'-?(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'


def _children(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for decl in re.finditer(rf'(?m)^[ \t]*{_INT}\s+({IDENT})\s*(?:=\s*({_LITERAL})\s*)?;[ \t]*\n', clean):
        if not part.opening < decl.start() < part.end:
            continue
        local, value = decl[1], decl[2]
        word = re.compile(rf'(?<![\w.>]){re.escape(local)}\b')
        uses = [hit for hit in word.finditer(clean, decl.end(), part.end)]
        removals = [(decl.start(), decl.end())]
        reads = []
        for hit in uses:
            after = clean[hit.end():part.end]
            before = clean[part.opening:hit.start()]
            store = re.match(rf'\s*=\s*({_LITERAL})\s*;[ \t]*\n?', after)
            if store and not re.search(r'[=!<>]\s*$', before) and value is None:
                value = store[1]
                line = clean.rfind('\n', 0, hit.start()) + 1
                if clean[line:hit.start()].strip():
                    break
                removals.append((line, hit.end() + store.end()))
                continue
            if re.match(r'\s*[!=]=', after) or re.search(r'[!=]=\s*$', before):
                reads.append(hit)
                continue
            break
        else:
            if value is None or not reads or len(removals) > 2:
                continue
            literal = f'({value})' if value.startswith('-') else value
            edits = sorted([(a, b, '') for a, b in removals] + [(h.start(), h.end(), literal) for h in reads],
                           reverse=True)
            text = source
            for start, end, new in edits:
                text = text[:start] + new + text[end:]
            out.append((FAMILY, text))
    return out[:LIMIT]


def variants(source, name):
    return _children(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
