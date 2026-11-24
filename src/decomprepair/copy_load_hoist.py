"""A copy statement's load read early into a local, the statement storing the local where it stood.

Matched on an N64 object initialiser built by SN's gcc 2.7.2 (`sn-n64-281`, `-G0 -mips2 -O2`), 31 instructions, 60 -> 0
with one edit. The draft's last statement copies a float member of the second record into the first
(`M2C_FIELD(dst, f32 *, 0xC) = (f32) M2C_FIELD(src, f32 *, 0xC);`) after four constant stores and a pointer store.
The target loads that member right after the float sum's store (`lwc1 $f0,0xc($s1)` between `swc1 $f0,8($s0)` and the
`addiu $v0,$zero,0x19`) and stores it at the very end, so two rows are out of order and nothing else differs. Written
as a local read at that place and stored last,

    f32 temp;  ...  dst[8] = src[8] + ...;  temp = (f32) src[0xC];  dst[0x64] = 0x19; ...  dst[0xC] = temp;

it was exact. gcc schedules a load no earlier than the statements that come before it in the source allow (it cannot
move a load above a store that may alias it), so the only way to put it above the four stores is to write it there.

`temporary_hoist` holds a sub-expression in a local and can move the assignment up, but it stops at the first statement
that may write memory (`_earliest`: "one that changes something the expression reads", which any store through another
pointer does for a load), so a copy that sits after stores was never offered the earlier position.

copy_load_hoist
    For each statement `LHS = [(T)] LOAD;` directly in a block, where LHS and LOAD are both cells of one scalar type T
    (`M2C_FIELD(base, T *, off)` or `*(T *)((s8 *)base + off)`, in either spelling, optionally parenthesised), and
    for each earlier store `S` of the same block: the load assigned to a new local right after `S`, the original
    statement storing the local. The local is declared with the function's own declarations. The same for an update
    of a cell (`CELL = (T) (CELL op e);` or `CELL op= e;`, alone or in a one-shot `do { } while (0)`): the cell is read
    into the local at the anchor, the write stays and uses the local, with the fence kept and dropped (and added to an
    unfenced one), 60 -> 0 on a 46-instruction method whose neighbour's update the read had to precede. A position is offered
    only when every statement between `S` and the copy is a plain assignment or a `do { } while (0)` of plain
    assignments, with no call, and none of them writes the load's base pointer or a cell of the same base whose bytes
    overlap the loaded cell's. Stores through another base pass: the original program read the cell after them, and
    that they do not overlap is the assumption the target's own order makes; the exact judge decides every child.
    The nearest `POSITIONS` anchors per copy statement, nearest first, at most `LIMIT` children.

A function with a `volatile` is left alone, and so is a cell the reader cannot type (a `->` member, a struct, a
pointer): the local needs the cell's type. Hypothesis from the match, not from the compiler source: the first
scheduler keeps loads and stores in their source order unless it can prove them apart.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'copy_load_hoist'
FAMILIES = (FAMILY,)
POSITIONS = 6
LIMIT = 48
SIZES = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 's64': 8, 'u64': 8, 'f64': 8}
NUMBER = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*'
_FIELD = rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*(?P<type>{IDENT})\s*\*\s*,\s*(?P<off>{NUMBER})\s*\)'
_DEREF = (rf'\*\s*\(\s*(?P<type2>{IDENT})\s*\*\s*\)\s*\(\s*\(\s*[su]8\s*\*\s*\)\s*(?P<base2>{IDENT})\s*'
          rf'\+\s*(?P<off2>{NUMBER})\s*\)')
CELL = re.compile(rf'(?:{_FIELD}|{_DEREF})')
_CALL = re.compile(rf'\b(?!M2C_FIELD\b|sizeof\b)({IDENT})\s*\(')
_ASSIGN = re.compile(r'(?P<lhs>[^=;{}]+?)\s*(?P<op>[-+*/%&|^]|<<|>>)?=(?!=)\s*(?P<rhs>[^;{}]+?)\s*;')
_WRAPPER = re.compile(r'do\s*\{(?P<inner>.*)\}\s*while\s*\(\s*0\s*\)\s*;', re.S)


def _cell(text):
    """(base, type, offset) when `text` is exactly one typed cell (maybe in parentheses), else None."""
    text = text.strip()
    while text.startswith('(') and text.endswith(')') and CELL.fullmatch(text[1:-1].strip()):
        text = text[1:-1].strip()
    found = CELL.fullmatch(text)
    if not found:
        return None
    kind = found['type'] or found['type2']
    if kind not in SIZES:
        return None
    return found['base'] or found['base2'], kind, int(re.sub(r'[uUlL]+$', '', found['off'] or found['off2']), 0)


def _brace_groups(clean, start, end):
    """(open, close) of each brace group at parenthesis depth 0 inside clean[start:end], outermost only."""
    groups, depth, opening = [], 0, None
    for i in range(start, end):
        c = clean[i]
        if c == '{':
            if depth == 0:
                opening = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and opening is not None:
                groups.append((opening, i))
    return groups


def _statements(clean, low, high):
    """(start, end) of each statement directly in clean[low:high]; a compound one ends at its closing brace, unless
    an `else` or a `while` continues it."""
    spans, depth, start, i = [], 0, None, low
    while i < high:
        c = clean[i]
        if start is None:
            if c.isspace():
                i += 1
                continue
            start = i
        if c in '({[':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == '}':
            depth -= 1
            if depth == 0 and not re.match(r'\s*(?:else|while)\b', clean[i + 1:high]):
                spans.append((start, i + 1))
                start = None
        elif c == ';' and depth == 0:
            spans.append((start, i + 1))
            start = None
        i += 1
    return spans


class _Plain:
    """What a statement writes, when it is a plain assignment or a `do { } while (0)` of them; else not crossable."""

    def __init__(self, text):
        self.stores = []  # lhs texts
        self.ok = self._read(text.strip())
        # a call statement: not crossable, but a position right after it is
        self.call = not self.ok and bool(re.fullmatch(rf'{IDENT}\s*\([^;{{}}]*\)\s*;', text.strip()))

    def _read(self, text):
        wrapped = _WRAPPER.fullmatch(text)
        if wrapped:
            inner = wrapped['inner']
            spans = _statements(inner, 0, len(inner))
            return bool(spans) and all(self._read(inner[a:b].strip()) for a, b in spans)
        found = _ASSIGN.fullmatch(text)
        if not found or _CALL.search(text) or re.search(r'\+\+|--|\bvolatile\b|\b(?:goto|return|break)\b', text):
            return False
        self.stores.append(found['lhs'].strip())
        return True


def _blocked(plains, base, low, high):
    """True when a statement between the anchor and the copy writes the base pointer or overlaps the loaded bytes."""
    for plain in plains:
        for lhs in plain.stores:
            if re.fullmatch(IDENT, lhs):
                if lhs == base:
                    return True
                continue
            cell = _cell(lhs)
            if cell is None:
                if re.search(rf'\b{re.escape(base)}\b', lhs):
                    return True
                continue
            if cell[0] == base and cell[2] < high and low < cell[2] + SIZES[cell[1]]:
                return True
    return False


def _fresh(clean):
    for number in range(100):
        name = 'temp_copy' if not number else f'temp_copy{number}'
        if not re.search(rf'\b{name}\b', clean):
            return name
    return None


def _after_declarations(clean, part):
    from .declaration_scope_sink_repairs import DECLARATION
    end = part.opening + 1
    for hit in DECLARATION.finditer(clean, part.opening + 1, part.end):
        if clean[end:hit.start('type')].strip():
            break
        end = hit.end()
    return clean.find('\n', end) + 1


def _line_indent(source, position):
    line = source.rfind('\n', 0, position) + 1
    return re.match(r'[ \t]*', source[line:]).group(0)


def _blocks(clean, low, high):
    """The function body and every block nested in it, as (low, high) of their contents."""
    yield low, high
    for opening, closing in _brace_groups(clean, low, high):
        yield from _blocks(clean, opening + 1, closing)


def _site(clean, span):
    """(core span, the statement written with TEMP, the assignment that fills TEMP, the loaded cell, wrapped,
    read-modify-write) for a copy `LHS = [(T)] LOAD;` or an update `CELL op= e;` (alone or in a one-shot fence)."""
    core, wrapped = span, False
    fence = _WRAPPER.fullmatch(clean[span[0]:span[1]])
    if fence:
        inner = _statements(clean, span[0] + fence.start('inner'), span[0] + fence.end('inner'))
        if len(inner) != 1:
            return None
        core, wrapped = inner[0], True
    found = _ASSIGN.fullmatch(clean[core[0]:core[1]])
    if not found:
        return None
    store = _cell(found['lhs'])
    if store is None:
        return None
    lhs, rhs = clean[core[0] + found.start('lhs'):core[0] + found.end('lhs')].strip(), found['rhs'].strip()
    if found['op']:
        value = rhs if re.fullmatch(rf'{NUMBER}|{IDENT}', rhs) else f'({rhs})'
        return core, f'{lhs} = TEMP {found["op"]} {value};', lhs, store, wrapped, True
    cast = re.fullmatch(rf'\(\s*({IDENT})\s*\)\s*(.+)', rhs, re.S)
    load = _cell(cast[2]) if cast and cast[1] == store[1] else _cell(rhs)
    if load is not None and load[1] == store[1]:
        return core, f'{lhs} = TEMP;', rhs, load, wrapped, False
    # `CELL = [(T)] (CELL op e);`, the update spelled out: the cell read first is held
    body = rhs[len(rhs) - len(cast[2]):] if cast and cast[1] == store[1] else rhs
    first = CELL.search(body)
    if (not first or _cell(first.group(0)) != store or body[:first.start()].strip('( \t')
            or not re.match(r'\s*(?:[-+*/&|^]|<<|>>)(?!=)', body[first.end():])):
        return None
    new = body[:first.start()] + 'TEMP' + body[first.end():]
    return core, f'{lhs} = {rhs[:len(rhs) - len(body)]}{new};', first.group(0), store, wrapped, True


def _swaps(source, clean, spans, plains, index, site):
    """The statement at `index` moved above the plain statements before it, one position per child, while it
    commutes with each: they neither touch its stored cell nor write the cell, the base or the names it reads."""
    core = site[0]
    text = clean[spans[index][0]:spans[index][1]]
    found = _ASSIGN.fullmatch(clean[core[0]:core[1]])
    store = _cell(found['lhs'])
    reads = [_cell(hit.group(0)) for hit in CELL.finditer(found['rhs'])]
    words = set(re.findall(IDENT, text))
    begin = source.rfind('\n', 0, spans[index][0]) + 1
    if source[begin:spans[index][0]].strip():
        return []
    finish = spans[index][1] + (1 if source[spans[index][1]:spans[index][1] + 1] == '\n' else 0)
    result = []
    for position in range(index - 1, -1, -1):
        crossed = plains[position:index]
        if not all(p.ok for p in crossed):
            break
        stores = [lhs for p in crossed for lhs in p.stores]
        if any(re.fullmatch(IDENT, lhs) and lhs in words or not re.fullmatch(IDENT, lhs) and _cell(lhs) is None
               for lhs in stores):
            break
        if any(_blocked(crossed, cell[0], cell[2], cell[2] + SIZES[cell[1]]) for cell in reads if cell):
            break
        mentioned = [_cell(hit.group(0)) for a, b in spans[position:index] for hit in CELL.finditer(clean[a:b])]
        if any(cell and cell[0] == store[0] and cell[2] < store[2] + SIZES[store[1]]
               and store[2] < cell[2] + SIZES[cell[1]] for cell in mentioned):
            break
        line = source.rfind('\n', 0, spans[position][0]) + 1
        if source[line:spans[position][0]].strip():
            break
        result.append((FAMILY, edit(source, [(begin, finish, ''), (line, line, source[begin:finish].rstrip('\n') + '\n')])))
        if len(result) >= POSITIONS:
            break
    return result


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[part.opening:part.end]):
        return []
    clean = part.clean
    temp = _fresh(clean)
    if temp is None:
        return []
    at = _after_declarations(clean, part)
    result = []
    for low, high in _blocks(clean, part.opening + 1, part.end - 1):
        spans = _statements(clean, low, high)
        plains = [_Plain(clean[a:b]) for a, b in spans]
        for index in range(len(spans) - 1, 0, -1):
            if not plains[index].ok:
                continue
            site = _site(clean, spans[index])
            if site is None:
                continue
            core, replacement, assigned, load, wrapped, modify = site
            offered = 0
            for anchor in range(index - 2, -1, -1):
                crossed = plains[anchor + 1:index]
                if not all(p.ok for p in crossed) or _blocked(crossed, load[0], load[2], load[2] + SIZES[load[1]]):
                    break
                if not (plains[anchor].ok and plains[anchor].stores or plains[anchor].call):
                    continue
                start = spans[anchor][1]
                indent = _line_indent(source, spans[anchor][0])
                hold = [(start, start, f'\n{indent}{temp} = {assigned.replace("TEMP", temp)};'),
                        (at, at, f'    {load[1]} {temp};\n')]
                text = replacement.replace('TEMP', temp)
                forms = [(core, text)]
                if modify:  # a read-modify-write: the write with and without its one-shot fence
                    forms.append((spans[index], text) if wrapped else (spans[index], f'do {{ {text} }} while (0);'))
                for span, new in forms:
                    result.append((FAMILY, edit(source, hold + [(span[0], span[1], new)])))
                offered += 1
                if offered >= POSITIONS:
                    break
            result.extend(_swaps(source, clean, spans, plains, index, site))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
