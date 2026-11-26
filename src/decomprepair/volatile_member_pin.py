"""Struct members made `volatile`, so a run of accesses through one record pointer keeps its source order.

`volatile_access_pin` marks two neighbouring cast accesses. This is the same rule for a record's members, where the
accesses need not be neighbours and one fixed-address load must still move above the run: sched.c makes two volatile
references depend on each other (`MEM_VOLATILE_P (x) && MEM_VOLATILE_P (mem)`) and leaves a plain scalar global free to
pass them, while a member store of a record ("in a struct" at a varying address) never aliases that global. On a
235-instruction SN64 GCC 2.8.1 N64 function the target stored a callback and -1 into a camera record, then read its
flag word, and loaded another global pointer above both stores. Plain members let the flag load rise above the stores
(525), a raw-offset store of the -1 held the global load below it (180), and `volatile` on exactly the three members,
with the -1 written as the member, matched (0).

For a run of adjacent simple statements, each holding one access to members of one `T *` pointer (`T` a typedef struct
of the source), a child makes one member that the run reads and one or two members it stored before that `volatile` in
the typedef. A raw `*(T2 *)((u8 *)p + 0x68) = v;` in the run is first written as the member at that offset. Proposals
only; the compiler and the byte judge decide."""
import itertools
import re

from .csource import _blank, find

FAMILY = 'volatile_member_pin'
FAMILIES = (FAMILY,)
LIMIT = 24

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_RECORD = re.compile(rf'typedef\s+struct(?:\s+{_ID})?\s*\{{(?P<body>[^{{}}]*)\}}\s*(?P<name>{_ID})\s*;')
_MEMBER = re.compile(rf'(?P<type>[A-Za-z_][\w\s]*?)(?P<stars>[\s*]*)\b(?P<name>{_ID})\s*(?:\[\s*(?P<count>{_NUM})\s*\])?\s*;')
_SIZES = {'u8': 1, 's8': 1, 'char': 1, 'unsigned char': 1, 'signed char': 1, 'u16': 2, 's16': 2, 'short': 2,
          'unsigned short': 2, 's32': 4, 'u32': 4, 'int': 4, 'unsigned int': 4, 'long': 4, 'f32': 4, 'float': 4,
          's64': 8, 'u64': 8, 'f64': 8, 'double': 8}
_RAW = re.compile(rf'\*\(\s*{_ID}[\s*]*\*\s*\)\s*\(\s*\(\s*(?:char|u8|s8)\s*\*\s*\)\s*(?P<base>{_ID})\s*\+\s*(?P<off>{_NUM})\s*\)')
_SKIP = re.compile(r'\s*(?:if|else|while|for|do|switch|case|default|return|goto|break|continue|typedef)\b')


def _records(clean):
    """{record name: {member: (offset or None, start, end of the declaration, start of the member's name, is pointer)}}."""
    records = {}
    for record in _RECORD.finditer(clean):
        members, at = {}, 0
        for part in _MEMBER.finditer(clean, *record.span('body')):
            pointer = '*' in part['stars']
            size = 4 if pointer else _SIZES.get(' '.join(part['type'].split()))
            if size is None:
                at = None  # a nested record: what follows has no offset we know
            elif at is not None:
                at = (at + size - 1) // size * size
            members[part['name']] = (at, part.start('type'), part.end(), part.start('name'), pointer)
            if at is not None:
                at += size * (int(part['count'], 0) if part['count'] else 1)
        records[record['name']] = members
    return records


def _runs(clean, opening, closing):
    """Lists of (start, end) of adjacent simple statements."""
    runs, run, start, depth = [], [], opening + 1, 0
    for at in range(opening + 1, closing):
        ch = clean[at]
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0 and ch in '{}:;':
            if ch == ';' and clean[start:at].strip() and not _SKIP.match(clean[start:at]):
                run.append((start, at + 1))
            else:
                runs.append(run)
                run = []
            start = at + 1
    runs.append(run)
    return [r for r in runs if len(r) > 1]


def _volatile(source, member):
    _, begin, _, name_at, pointer = member
    if pointer:
        return name_at, name_at, 'volatile '
    return begin, begin, 'volatile '


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    records = _records(clean)
    if not records:
        return []
    pointers = {m['var']: m['type'] for m in re.finditer(
        rf'\b(?P<type>{"|".join(map(re.escape, records))})\s*\*\s*(?P<var>{_ID})\b', clean[span[0]:span[1]])}
    runs = _runs(clean, opening, closing)
    found = []
    for var, kind in pointers.items():
        members = records[kind]
        by_offset = {info[0]: member for member, info in members.items() if info[0] is not None}
        access = re.compile(rf'(?<![\w.>])(?<!->){re.escape(var)}\s*->\s*(?P<member>{_ID})(?!\s*(?:->|\.|\[))')
        for statements in runs:
            # one (member, loads, raw rewrite) per statement; a statement without one ends the group
            group = []
            for begin, end in statements + [(closing, closing)]:
                text = clean[begin:end]
                plain = [m for m in access.finditer(text) if m['member'] in members]
                raw = [m for m in _RAW.finditer(text) if m['base'] == var and int(m['off'], 0) in by_offset]
                if len(plain) + len(raw) != 1:
                    if len(group) > 1:
                        found.extend(_children(source, members, var, group))
                    group = []
                    continue
                hit = (plain or raw)[0]
                member = hit['member'] if plain else by_offset[int(hit['off'], 0)]
                after = text[hit.end():]
                stored = not text[:hit.start()].strip() and re.match(r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', after)
                loads = not stored or not re.match(r'\s*=(?!=)', after)
                rewrite = (begin + hit.start(), begin + hit.end(), f'{var}->{member}') if raw else None
                group.append((member, loads, rewrite))
    out, seen = [], set()
    for _, _, text in sorted(found, key=lambda item: item[:2]):
        if text not in seen:
            seen.add(text)
            out.append((FAMILY, text))
    return out[:LIMIT]


def _children(source, members, var, group):
    """(rank, position, source) for each choice of one loaded member and the one or two members stored before it."""
    raws = [rewrite for _, _, rewrite in group if rewrite]
    for at, (loaded, loads, _) in enumerate(group):
        if not loads:
            continue
        stored = list(dict.fromkeys(member for member, load, _ in group[:at] if not load and member != loaded))
        # the first stores of the run first, pairs before single stores
        choices = [(0, pair) for pair in itertools.combinations(range(len(stored)), 2)]
        choices += [(1, (one,)) for one in range(len(stored))]
        for kind, picked in sorted(choices, key=lambda c: (max(1, max(c[1])), c[0], c[1]))[:LIMIT]:
            pins = [stored[i] for i in picked] + [loaded]
            if any('volatile' in source[members[m][1]:members[m][2]] for m in pins):
                continue
            edits = raws + [_volatile(source, members[m]) for m in pins]
            text = source
            for begin, end, new in sorted(edits, reverse=True):
                text = text[:begin] + new + text[end:]
            yield (max(1, max(picked)), kind, picked), at, text


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
