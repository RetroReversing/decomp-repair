"""A store to a struct member moved up past the plain statements before it that read other members of that struct.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) scroll-window update that stood at 1380: a halfword member
was updated (`w->offset += delta;`) after two statements that read the byte members `w->scroll`, `w->scale` and
`w->count` into locals. The target loads `scroll` and `scale` a second time after the store (cse keeps no byte load
across a halfword store through the same base), so its first product is computed from the first loads and its second
from fresh ones; written after the reads, cse merged the loads and the frame, the register order and the load
positions all differed. Moving the store up past the two reads (1380 -> 985, 31 differing rows fewer) is the whole fix.
`statement_slide` does this for `M2C_FIELD` cells only; a typed record's `->` members were never offered.

member_store_hoist
    `a = ..w->x..; b = ..w->y..; w->f op= e;` becomes `w->f op= e; a = ..; b = ..;` for one to four preceding
    statements. A child is offered only when the moved statement commutes with every statement it passes: no call, no
    dereference or index, no `volatile`, no local one writes that the other reads or writes, and no member of the same
    name (through any pointer) that one writes and the other touches. Hypothesis from the match, not from the compiler
    source: a store through a base invalidates cse's cached loads of the members it may overlap, so where it sits among
    the loads decides which of them are reloaded.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'member_store_hoist'
FAMILIES = (FAMILY,)
REACH = 4
LIMIT = 8
_MEMBER = re.compile(rf'\b({IDENT})\s*->\s*({IDENT})\b')
_STORE = re.compile(rf'(?P<lhs>{IDENT}\s*->\s*{IDENT})\s*(?P<op>[-+*&|^]|<<|>>)?=(?!=)\s*(?P<rhs>[^;{{}}]+?)\s*;')
_SIMPLE = re.compile(rf'(?P<lhs>{IDENT}(?:\s*->\s*{IDENT})?)\s*(?P<op>[-+*&|^]|<<|>>)?=(?!=)\s*(?P<rhs>[^;{{}}]+?)\s*;')
_UNARY = r'(?:^|[=(,?:!~<>+\-/%|^&*])\s*'
_REJECT = re.compile(rf'\[|\.|{_UNARY}[&*]|\+\+|--|\bvolatile\b|\b{IDENT}\s*\(')
_TYPES = r'(?:u8|s8|u16|s16|u32|s32|int|char|short|unsigned|signed|f32|sizeof)'


def _effects(statement):
    """(writes, reads) as ('v', name) and ('m', base, field) keys for one plain assignment, or None."""
    found = _SIMPLE.fullmatch(statement.strip())
    if not found:
        return None
    lhs, rhs, compound = found['lhs'], found['rhs'], found['op'] is not None
    if _REJECT.search(rhs) or re.search(r'\b(?:return|goto|break|continue)\b', rhs):
        return None
    member = _MEMBER.fullmatch(lhs.strip())
    write = ('m', member[1], member[2]) if member else ('v', lhs.strip())
    reads = {write} if compound else set()
    for hit in _MEMBER.finditer(rhs):
        reads.add(('m', hit[1], hit[2]))
    reads |= {('v', ident) for ident in re.findall(IDENT, _MEMBER.sub(' ', rhs)) if not re.fullmatch(_TYPES, ident)}
    if member:  # the base pointer is read
        reads.add(('v', member[1]))
    return {write}, reads


def _touches(key, effects):
    """True when `key` (a write) clashes with a write or a read in `effects`."""
    writes, reads = effects
    everything = writes | reads
    if key in everything:
        return True
    if key[0] == 'm':
        return any(other[0] == 'm' and other[2] == key[2] for other in everything)
    return False


def _commutes(moved, passed):
    if any(_touches(key, passed) for key in moved[0]):
        return False
    return not any(_touches(key, moved) for key in passed[0])


def _children(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, result = part.clean, []
    for store in _STORE.finditer(clean, part.opening + 1, part.end):
        line_start = clean.rfind('\n', 0, store.start()) + 1
        if clean[line_start:store.start()].strip():
            continue
        before = clean[part.opening + 1:line_start].rstrip()
        if not before or before[-1] not in ';{':
            continue
        moved = _effects(store.group(0))
        if not moved:
            continue
        passed, cursor = [], line_start
        while len(passed) < REACH:
            head = clean[part.opening + 1:cursor].rstrip()
            if not head.endswith(';'):
                break
            start = max(head.rfind(';', 0, len(head) - 1), head.rfind('{'), head.rfind('}')) + 1
            absolute = part.opening + 1 + start
            text = clean[absolute:part.opening + 1 + len(head)]
            line = clean.rfind('\n', 0, absolute + len(text) - len(text.lstrip())) + 1
            if clean[line:absolute + len(text) - len(text.lstrip())].strip():
                break
            effects = _effects(text.strip())
            if not effects or not _commutes(moved, effects):
                break
            passed.append(line)
            cursor = line
            if len(passed) >= 1:
                moved_text = source[line_start:store.end()]
                end = store.end()
                tail = source[end:end + 1]
                removal_end = end + (1 if tail == '\n' else 0)
                if not moved_text.endswith('\n'):
                    moved_text += '\n'
                rest = source[:line_start] + source[removal_end:]
                result.append((FAMILY, rest[:line] + moved_text + rest[line:]))
    return result[:LIMIT]


def variants(source, name):
    return _children(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
