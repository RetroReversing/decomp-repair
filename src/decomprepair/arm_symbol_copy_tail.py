"""A copy m2c made once after an `if`/`else`, through a pointer each arm aimed at a symbol, written in every arm.

A game picks one of two matrices and copies it: `if (flag == 0) { emit(a); current = cameraA; } else { emit(b);
current = cameraB; }`. Each arm is a copy from a known symbol, and jump2 merges the two identical tails after
allocation, so the object has one store run that both arms reach and each arm still loads its first word through
`%lo(symbol)`. m2c reads the merged tail back with variables each arm set:

    if (c) { ...; first = A;  src = &A; }            if (c) { ...; M2C_FIELD(&D, s32 *, 0) = A;
    else   { ...; first = B;  src = &B; }    ->               M2C_FIELD(&D, s32 *, 4) = M2C_FIELD((&A), s32 *, 4); ... }
    M2C_FIELD(&D, s32 *, 0) = first;                 else   { the same from B }
    M2C_FIELD(&D, s32 *, 4) = (s32) ((Rec *) src)->m4;
    ...

With the pointer a variable it is a pseudo live across the whole copy and the registers of the loads shift. The copy
must also be written from the symbol with the plain word cast: a member read through the draft's record is a
structure access to alias analysis, which orders the loads and stores differently. Measured on a 75-instruction N64
display-list and matrix load (SN GCC 2.8.1, `-O2 -G0 -mips3`): the machine draft judged 3950, this child 1080 (the
member spelling 1600), and with `command_post_increment` for the display-list writes it was byte-identical. One
function.

The first child writes record members through the pointer as word casts at the member's offset; the second keeps the
members and only substitutes the symbol. A value variable (`first` above) must be read by the first statement of the
tail alone, so that no store of the copy comes between the arm's read and its use."""
import re

from .arm_block_support import statements
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'arm_symbol_copy_tail'
FAMILIES = (FAMILY,)
LIMIT = 4
ID = r'[A-Za-z_]\w*'
SETTING = re.compile(rf'(?P<v>{ID})\s*=\s*(?P<amp>&\s*)?(?P<symbol>{ID})\s*;')
IF = re.compile(r'\bif\s*\(')
SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4,
         'float': 4}
MEMBER = re.compile(rf'(?P<type>(?:(?:unsigned|signed|struct)\s+)?{ID})\s*(?P<star>\**)\s*(?P<name>{ID})\s*'
                    r'(?:\[\s*(?P<count>0[xX][0-9a-fA-F]+|\d+)\s*\])?$')


def _blocks(clean, at):
    """((then open, then close), (else open, else close)) of the braced two-arm `if` at `at`, or None."""
    condition = close(clean, clean.index('(', at), '(', ')')
    if not condition:
        return None
    found, position = [], condition
    for part in range(2):
        if part:
            other = re.compile(r'\s*else\b').match(clean, position)
            if not other:
                return None
            position = other.end()
        opening = re.compile(r'\s*\{').match(clean, position)
        if not opening:
            return None
        position = close(clean, opening.end() - 1, '{', '}')
        if not position:
            return None
        found.append((opening.end() - 1, position - 1))
    return found


def _members(source, record):
    """{member: (offset, pointee type)} of `typedef struct { .. } record;` with scalar, pointer and array members."""
    found = re.search(rf'typedef\s+struct\s*(?:{ID}\s*)?\{{(?P<body>[^{{}}]*)\}}\s*{record}\s*;', _blank(source))
    if not found:
        return {}
    offset, members = 0, {}
    for declaration in found['body'].split(';'):
        if not declaration.strip():
            continue
        member = MEMBER.match(declaration.strip())
        size = 4 if member and member['star'] else SIZES.get(member['type']) if member else None
        if not size:
            break  # (what follows has an unknown offset)
        offset = (offset + size - 1) // size * size
        if not member['count']:
            members[member['name']] = (offset, member['type'] + (' ' + member['star'] if member['star'] else ''))
        offset += size * int(member['count'] or '1', 0)
    return members


def _substituted(source, text, settings, casts):
    """`text` with each variable replaced by what the arm set it to."""
    macro = re.search(r'^\s*#\s*define\s+M2C_FIELD\b', source, re.M)
    for variable, (address, symbol) in settings.items():
        value = f'(&{symbol})' if address else symbol
        if address and casts:
            def read(match, value=value):
                member = _members(source, match['record']).get(match['member'])
                if not member:
                    return match.group()
                offset, kind = member
                if macro:
                    return f'M2C_FIELD({value}, {kind} *, {offset:#x})'
                return f'(*({kind} *) ((signed char *) {value} + {offset:#x}))'
            text = re.sub(rf'\(\s*\(\s*(?P<record>{ID})\s*\*\s*\)\s*{variable}\s*\)\s*->\s*(?P<member>{ID})',
                          read, text)
        text = re.sub(rf'(?<![\w.])(?<!->){variable}\b', value, text)
    return text


def _settings(clean, block):
    """({variable: (is an address, symbol)}, spans) of the assignments of symbols that end an arm."""
    found, spans = {}, []
    for start, end in reversed(statements(clean, block[0] + 1, block[1])):
        setting = SETTING.fullmatch(clean[start:end])
        if not setting or setting['v'] in found:
            break
        found[setting['v']] = (bool(setting['amp']), setting['symbol'])
        spans.append((start, end))
    return found, spans


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0 or '#' in clean[opening:span[1]]:
        return []
    out = []
    for hit in IF.finditer(clean, opening, span[1]):
        blocks = _blocks(clean, hit.start())
        if not blocks:
            continue
        first, second = (_settings(clean, block) for block in blocks)
        shared = [v for v in first[0] if v in second[0]]
        if not shared or not any(first[0][v][0] and second[0][v][0] for v in shared):
            continue
        if any(first[0][v][0] != second[0][v][0] for v in shared):
            continue
        # the statements after the chain, up to the last that reads one of the variables
        end = blocks[1][1] + 1
        tail = []
        for start, stop in statements(clean, end, span[1]):
            text = clean[start:stop]
            if '{' in text or '}' in text or re.match(rf'(?:return|goto|break|continue|if|for|while|do|switch)\b'
                                                      rf'|(?:case\b[^:;]*|{ID}\s*):(?!:)', text):
                break
            tail.append((start, stop))
        reads = [i for i, (a, b) in enumerate(tail) if any(re.search(rf'\b{v}\b', clean[a:b]) for v in shared)]
        if not reads:
            continue
        tail = tail[:reads[-1] + 1]
        body = clean[tail[0][0]:tail[-1][1]]
        rest = clean[tail[0][1]:tail[-1][1]]
        usable = True
        for variable in shared:
            inside = len(re.findall(rf'(?<![\w.])(?<!->){variable}\b', body))
            total = len(re.findall(rf'(?<![\w.])(?<!->){variable}\b', clean[opening:span[1]]))
            changed = re.search(rf'\b{variable}\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)|(?:\+\+|--|[(,=]\s*&)\s*{variable}\b',
                                body)
            # (the declaration, one assignment an arm, and the tail's reads: nothing else)
            if not inside or changed or total != inside + 3:
                usable = False
            if not first[0][variable][0] and re.search(rf'\b{variable}\b', rest):
                usable = False
        if not usable:
            continue
        text = source[tail[0][0]:tail[-1][1]]
        for casts in (True, False):
            edits = [(len(source[:tail[0][0]].rstrip()), tail[-1][1], '')]
            for block, (settings, spans) in zip(blocks, (first, second)):
                chosen = {v: settings[v] for v in shared}
                edits.extend((len(source[:a].rstrip()), b, '') for a, b in spans
                             if SETTING.fullmatch(clean[a:b])['v'] in chosen)
                copy = _substituted(source, text, chosen, casts)
                edits.append((block[1], block[1], '    ' + copy.replace('\n', '\n    ') + '\n    '))
            child = source
            for a, b, new in sorted(edits, reverse=True):
                child = child[:a] + new + child[b:]
            if all(child != other for _, other in out):
                out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}
