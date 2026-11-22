"""A mask's complement computed just before the operation that uses it, and volatile member reads written plain.

From a 110-instruction N64 heap allocator (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): one arm of a bump
allocator rounds a pointer up, `temp = old + mask; start = temp & inverse;`, with `inverse = ~mask` at the head of the
arm (`arm_invariant_sink` put it there, in a one-shot scope, so the branch's delay slot takes the `nor`). The target
keeps the mask out of `$v1` (`$a2`), the sum in `$v1` and the complement and the result in `$v0`. With the complement
first, the mask dies at the sum: nothing in `$v1` is live with it, so global.c gives it `$v1` (and the sum, the
complement and the result exchanged registers: 15 rows short of a match). Written after the sum, the complement is
the mask's last use, the mask is live when the sum is born and cannot share its register; written `inverse & temp`,
local-alloc.c (`combine_regs`, first dying operand first) ties the result to the complement. That alone put every
register right but left the `nor` out of the delay slot (165): the branch's slot is filled by reorg.c
`fill_slots_from_thread`, which looks past the arm's loads for an insn it may move, and it did not take the `nor`
from behind a `volatile` struct-member load (`used = D_800CE354[tag].used` with `volatile u32 used;` in the struct).
Read through `*(u32 *)&...` (a plain load) the slot took the `nor` (5), and the last row went with
`disjoint_local_merge_swap` (0). The reading of reorg.c is a hypothesis: the measurement is that the same source with
the member read volatile left the slot empty and with it plain filled it.

Families:
* `complement_late`: `x = ~m;` (alone or in `do { } while (0);`) moved to just before the one statement that reads
  `x` as an operand of `&`, `|` or `^`, in the same block, with the operands in both orders;
* `volatile_member_read_plain`: an assignment that reads a struct member the source declares `volatile`, written
  through a cast to the plain type (each read alone, then all of them);
* `complement_late_plain_reads`: both at once (each was no better alone: 15 -> 165 and 15 -> 15).
Candidates for the exact judge, never a verdict."""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'complement_late'
PLAIN_FAMILY = 'volatile_member_read_plain'
BOTH_FAMILY = 'complement_late_plain_reads'
FAMILIES = (FAMILY, PLAIN_FAMILY, BOTH_FAMILY)
LIMIT = 12
COMPLEMENT = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?:do\s*\{{\s*(?P<a>{IDENT})\s*=\s*~\s*(?P<m1>{IDENT})\s*;\s*\}}\s*while\s*\(\s*0\s*\)\s*;'
                        rf'|(?P<b>{IDENT})\s*=\s*~\s*(?P<m2>{IDENT})\s*;)[ \t]*\n')
MEMBER = re.compile(rf'\bvolatile\s+(?P<type>(?:unsigned\s+|signed\s+)?{IDENT})\s+(?P<field>{IDENT})\s*;')


def _mentions(text, name):
    return list(re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', text))


def _block_end(clean, at):
    depth = 0
    for index in range(at, len(clean)):
        if clean[index] == '{':
            depth += 1
        elif clean[index] == '}':
            if depth == 0:
                return index
            depth -= 1
    return len(clean)


def complement_late(source, name):
    """[(source, start, block_end)] (the rest of the block from where it was) for each complement moved to just before its use, in both operand orders."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in COMPLEMENT.finditer(clean, part.opening, part.end):
        x, mask = hit['a'] or hit['b'], hit['m1'] or hit['m2']
        end = _block_end(clean, hit.end())
        later = _mentions(clean[hit.end():part.end], x)
        if len(later) != 1 or hit.end() + later[0].start() > end:
            continue
        line_start = clean.rfind('\n', 0, hit.end() + later[0].start()) + 1
        line_end = clean.find('\n', line_start)
        use = re.match(rf'(?P<indent>[ \t]*)(?P<y>{IDENT})\s*=\s*(?P<l>{IDENT})\s*(?P<op>[&|^])\s*(?P<r>{IDENT})\s*;[ \t]*$',
                       clean[line_start:line_end])
        if not use or x not in (use['l'], use['r']) or use['l'] == use['r']:
            continue
        other = use['r'] if use['l'] == x else use['l']
        between = clean[hit.end():line_start]
        if re.search(rf'(?<![\w.>]){re.escape(mask)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+\s*{re.escape(mask)}\b|'
                     rf'\b{re.escape(mask)}\s*\+\+', between) or '{' in between or '}' in between:
            continue
        if not re.search(rf'(?<![\w.>]){re.escape(other)}\s*=(?!=)', between):
            continue  # the other operand is computed in between: that is what puts the complement after it
        indent = use['indent']
        for left, right in ((other, x), (x, other)):
            text = (source[:hit.start()] + source[hit.end():line_start] + f'{indent}{x} = ~{mask};\n'
                    + f"{indent}{use['y']} = {left} {use['op']} {right};" + source[line_end:])
            shift = hit.end() - hit.start()
            out.append((text, hit.start(), end - shift + len(f'{indent}{x} = ~{mask};\n')))
    return out


def plain_reads(source, name, start=None, end=None):
    """Sources with reads of `volatile` struct members (between `start` and `end`) written through plain casts."""
    part = view(source, name)
    if not part:
        return []
    fields = {m['field']: re.sub(r'\s+', ' ', m['type']) for m in MEMBER.finditer(source[:part.opening])}
    if not fields:
        return []
    lo, hi = start if start is not None else part.opening, end if end is not None else part.end
    reads = []
    pattern = re.compile(rf'(?m)^([ \t]*{IDENT}\s*=\s*)(?P<lv>{IDENT}(?:\s*\[[^\]\n]*\])?\s*(?:\.|->)\s*(?P<f>{IDENT}))\s*;')
    for hit in pattern.finditer(part.clean, lo, hi):
        if hit['f'] in fields:
            reads.append((hit.start('lv'), hit.end('lv'), f"*({fields[hit['f']]} *)&{source[hit.start('lv'):hit.end('lv')]}"))
    out = []

    def apply(edits):
        text = source
        for a, b, replacement in sorted(edits, reverse=True):
            text = text[:a] + replacement + text[b:]
        return text
    if len(reads) > 1:
        out.append(apply(reads))
    out.extend(apply([read]) for read in reads)
    return out


def variants(source, name):
    out = []
    for text, start, end in complement_late(source, name):
        out.append((FAMILY, text))
        for plain in plain_reads(text, name, start, end)[:1]:
            out.append((BOTH_FAMILY, plain))
    out.extend((PLAIN_FAMILY, text) for text in plain_reads(source, name)[:4])
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 93}  # the registry: no caller wiring (registry.py)
