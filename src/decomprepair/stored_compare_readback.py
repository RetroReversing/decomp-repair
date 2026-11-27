"""A field the function has just stored from a local, read back by a later condition instead of the local.

An N64 timer update (SN GCC 2.8.1, `-G0 -mips3 -O2 -mgas`, 23 instructions) bumped a record's word counter, stored
three bytes of the same record, and tested the counter. m2c kept the sum in a local and tested the local:

    t = *(s32 *)((s8 *)arg0 + 0x34) + 1;
    *(s32 *)((s8 *)arg0 + 0x34) = t;
    *(u8 *)((s8 *)arg0 + 0x73) = x + 1;
    ...
    if (t >= 0x3D) {

The target copies the stored register into another one (`addu $a0,$v0,$zero`) before the byte stores overwrite it and
tests the copy (`slti $a0,$a0,0x3D`). The game tested the member itself:

    if (*(s32 *)((s8 *)arg0 + 0x34) >= 0x3D) {

The compiler already has the value in a register, so the read costs no load; it is the copy that gives the target's
registers (330 -> 0; no family offered it). `stored_member_readback` reads back 8 and 16 bit members at a mask or cast
with only locals written between; this is the plain compare of a local of the member's own type, with stores to other
members of the same record in between.

A proposal takes `L = t;` (`L` a field `*(T *)((s8 *)p + K)`, `M2C_FIELD(p, T *, K)` or `p->m` whose type is `t`'s
declared type) and the next `if` of the same block, with only plain statements between that write a local or a field of
the same `p` that does not overlap `L`, call nothing and leave `t` and `p` alone. The condition's reads of `t` are
written as `L`. The member still holds `t` there, so the program is the same (two different names of one `->` record
are taken to be two members: a source with a `union` is left alone). This module reads text only and never compiles or
judges.

`stored_compare_readback_dead_copy` is the same read behind a search's broken scaffolding. The kept best of the case above
stored a local that only a dead block ever set:

    if (0) { copy = t; do { goto label; } while (0); }
    *(s32 *)((s8 *)arg0 + 0x34) = copy;

GCC happens to give `copy` and `t` one register, but the C reads an unset local. The child writes `t` where `copy` was
read, drops the dead jumps and their labels (`frame_fence_strip`) and then reads the field back (140 -> 0)."""
import re

from .frame_fence_strip import strip_goto
from .hand_found_support import (
    IDENT,
    NUMBER,
    blocks,
    calls_in,
    field_size,
    local_type,
    number,
    simple,
    stmts,
    store_target,
    writes,
)
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'stored_compare_readback'
FAMILY_DEAD_COPY = 'stored_compare_readback_dead_copy'
FAMILIES = (FAMILY, FAMILY_DEAD_COPY)
MAX_CHILDREN = 8
WINDOW = 12  # statements after the store before the `if`

_TYPE = r'[A-Za-z_][\w ]*?(?:\s*\*+)?'
_CAST = re.compile(rf'\*\s*\(\s*(?P<kind>{_TYPE})\s*\*\s*\)\s*\(\s*\(\s*(?:s8|u8|char|signed char|unsigned char)\s*\*\s*\)\s*'
                   rf'(?:\(\s*(?P<wrapped>{IDENT})\s*\)|(?P<base>{IDENT}))\s*\+\s*(?P<offset>{NUMBER})\s*\)')
_MACRO = re.compile(rf'M2C_FIELD\s*\(\s*(?P<base>{IDENT})\s*,\s*(?P<kind>{_TYPE})\s*\*\s*,\s*(?P<offset>{NUMBER})\s*\)')
_ARROW = re.compile(rf'(?P<base>{IDENT})\s*->\s*(?P<member>{IDENT})')


def _spelled(kind):
    return ' '.join(kind.replace('*', ' * ').split())


def _field(clean, part, text):
    """(base, type or None, offset or member name) of a field written one of the three ways; None for anything else."""
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text):
        text = text[1:-1].strip()
    hit = _CAST.fullmatch(text) or _MACRO.fullmatch(text)
    if hit:
        base = hit['base'] or hit.groupdict().get('wrapped')
        return base, _spelled(hit['kind']), number(hit['offset'])
    hit = _ARROW.fullmatch(text)
    if not hit:
        return None
    # The member's type as a struct of this source declares it, once.
    declared = re.findall(rf'(?<=[;{{])\s*({_TYPE})(?:(?<=\*)|\s)\s*{hit["member"]}\s*;', clean[:part.opening])
    return hit['base'], _spelled(declared[0]) if len(declared) == 1 else None, hit['member']


def _apart(stored, other):
    """True when the two fields of one base cannot share a byte."""
    if other is None or stored[0] != other[0] or isinstance(stored[2], str) != isinstance(other[2], str):
        return False
    if isinstance(stored[2], str):
        return stored[2] != other[2]
    sizes = [field_size(kind + ' *') for kind in (stored[1], other[1])]
    if None in sizes:
        return False
    return stored[2] + sizes[0] <= other[2] or other[2] + sizes[1] <= stored[2]


_DEAD_COPY = re.compile(rf'\bif\s*\(\s*0\s*\)\s*\{{\s*(?P<copy>{IDENT})\s*=(?!=)\s*(?P<value>{IDENT})\s*;\s*(?:do\s*)?(?:\{{\s*)?'
                        rf'goto\s+(?P<label>{IDENT})\s*;(?:\s*\}}(?:\s*while\s*\(\s*0\s*\)\s*;)?)?\s*\}}')


def _collapse_dead_copy(source, name):
    """The source with a local that only a dead block sets read as the local it copies there; None without one."""
    part = view(source, name)
    if not part:
        return None
    hit = _DEAD_COPY.search(part.clean, part.opening, part.end)
    if not hit:
        return None
    copy, value, body = hit['copy'], hit['value'], part.clean[part.opening:part.end]
    sets = r'(?<![\w.>]){}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)'
    if (not local_type(part, copy) or local_type(part, copy) != local_type(part, value)
            or len(re.findall(sets.format(copy), body)) != 1 or len(re.findall(sets.format(value), body)) != 1
            or re.search(rf'(?:&|\+\+|--)\s*(?:{copy}|{value})\b|\b(?:{copy}|{value})\s*(?:\+\+|--)', body)):
        return None
    reads = [m for m in re.finditer(rf'(?<![\w.>]){copy}\b(?!\s*=(?!=))', part.clean[:part.end]) if m.start() >= hit.end()]
    assigned = re.search(sets.format(value), body)
    if not reads or part.opening + assigned.start() > reads[0].start():
        return None
    edits = [(hit.start(), hit.end(), f'if (0) {{ goto {hit["label"]}; }}')] + [(m.start(), m.end(), value) for m in reads]
    # `if (0)` on a line of its own is what the dead-jump strip removes, labels and all.
    return strip_goto(edit(source, edits), name)


def variants(source, name):
    """Proposals: the condition after a field store reads the field instead of the local stored there; also behind a
    dead block that was the only set of the stored local."""
    out = [(FAMILY, child) for child in _readbacks(source, name)]
    collapsed = _collapse_dead_copy(source, name)
    if collapsed:
        out += [(FAMILY_DEAD_COPY, child) for child in _readbacks(collapsed, name)]
    return list(dict.fromkeys(out))[:MAX_CHILDREN]


def _readbacks(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:union|asm|__asm__)\b', part.clean):
        return []
    clean = part.clean
    out = []
    for lo, hi in blocks(part):
        spans = stmts(part, lo, hi)
        for k, (start, end) in enumerate(spans):
            hit = simple(clean[start:end]) and store_target(clean[start:end])
            if not hit or not re.fullmatch(IDENT, hit[1]):
                continue
            lvalue, local = hit
            stored = _field(clean, part, lvalue)
            kind = local_type(part, local)
            if not stored or not stored[1] or not kind or _spelled(kind) != stored[1] or stored[0] == local:
                continue
            for a, b in spans[k + 1:k + 1 + WINDOW]:
                text = clean[a:b]
                head = re.match(r'\s*if\s*\(', text)
                if head:
                    opening = a + head.end() - 1
                    stop = close(clean, opening, '(', ')')
                    condition = clean[opening:stop] if stop else ''
                    if not stop or calls_in(condition) or writes(condition, local) or re.search(r'\+\+|--', condition):
                        break
                    reads = [(opening + m.start(), opening + m.end()) for m in
                             re.finditer(rf'(?<![\w.>&]){local}\b(?!\s*(?:\[|\.|->|\())', condition)]
                    spelled = source[start:end]
                    written = spelled[spelled.index(spelled.strip()[0]):].split('=', 1)[0].strip()
                    if reads and written == lvalue.strip():
                        read = f'({written})' if written.startswith('*') else written
                        out.append(edit(source, [(x, y, read) for x, y in reads]))
                    break
                assigned = simple(text) and not calls_in(text) and not re.search(r'\+\+|--', text) and store_target(text)
                if not assigned:
                    break
                target = assigned[0].strip()
                if re.fullmatch(IDENT, target):
                    if target in (local, stored[0]) or not local_type(part, target):
                        break
                elif not _apart(stored, _field(clean, part, target)):
                    break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 67,
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
