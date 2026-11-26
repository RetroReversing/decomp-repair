"""Pointer tables read with one index in a loop: a user pointer for the table loop.c should hoist, a slot per table.

Two N64 triangle walkers (SN64 GCC 2.8.1, `-mfp32`) read a vertex pointer and a triangle pointer from two tables of
pointers indexed by the same model number at the top of their loop:

    vtx = VERTS[o->model];
    tri = &FACES[o->model][LIST[i].tri];

The target hoists one table's address out of the loop (rematerialised in `$t0` every iteration) and keeps the other
one's `lui/addiu` inside it. gcc-2.8.1's loop.c (`move_movables`) moves an invariant only when
`threshold * savings * lifetime >= insn_count`, the threshold dropping by 3 with every move: a table address written
`&T[m]` or `T + m` is expanded after the index load and lives 2 insns, which a loop of 263 insns never finds
desirable, while an rvalue `T[m]` lives 3-4 and is moved. So the table that is hoisted follows the spelling, and no
spelling of the two statements moved the right one (a 70-spelling grid on the ray test stalled at 55). A user pointer
set to the table at the body's top lives across the statements before its use and is the one moved:

    tt = FACES;
    o = LIST[i].obj;
    ts = &tt[o->model];
    vs = &VERTS[o->model];
    tri = &(*ts)[LIST[i].tri];
    vtx = *vs;

With the table pointer alone the loop head's order was the target's but the registers were not (185, with each
pointer staged through itself); one slot pointer per table, the loads after both slots, gave the target's allocation:
the 438-instruction ray test went 55 -> 0 and the 761-instruction shadow walker 195 -> 0 (each three edits; any two of
them 185-615). The loop.c rule is read from gcc-2.8.1's source and the `-dL` dump ("not desirable" for the life-2
address); that the slot pointers decide the allocation through local-alloc's priorities is a hypothesis, and the judge
decides each child.

Children (`loop_table_slot_pointers`, bounded): for a run of two or more consecutive statements in a loop body that
each read a pointer local `V` (declared `T *V`) from a table `SYM[E]` with one and the same plain index `E`, in any of
the forms `V = SYM[E];`, `V = SYM[E] + K;`, `V = &SYM[E][K];` or staged through `V` itself (`V = (T *) &SYM[E];`
then `V = *(T **) V ...;`, decomp-repair `table_slot_self_stage`), the rewrite above with each table as the hoisted
one, the slots in the run's order or the hoisted table's first, and the table pointer at the body's top or right
before the run.

The reads may be block-scope declarations with initialisers (`Vert *verts = VERTS[type];` at the top of the loop body,
m2c's and a clean rewrite's spelling): those lines are offered split into declarations and assignments first, and the
table pointer then goes after the body's declarations, where C89 allows a statement. Until then the `top` child of
such a body put the statement above the declarations and spliced the new declarations at a stale offset, so it never
compiled (a 537-instruction N64 collision ray test, SN64 GCC 2.8.1: its plain form 5029 -> 4689, `-mfp32` 3629 -> 3109,
with the triangle table hoisted and one slot per table).
"""
import re

from . import c_scan
from .csource import _blank, find

FAMILY = 'loop_table_slot_pointers'
FAMILIES = (FAMILY,)
LIMIT = 8
IDENT = r'[A-Za-z_]\w*'


def variants(source, name):
    return [(FAMILY, text) for text in rewrites(source, name)]


def _bracket(text, at):
    """The index of the `]` closing the `[` at `at` within its statement, or -1."""
    close = c_scan.close(text, at, '[', ']')
    stop = min((i for i in (text.find(c, at) for c in ';{}') if i >= 0), default=len(text))
    return close if 0 <= close < stop else -1


def _names(expr, var):
    return re.search(rf'(?<![\w.>]){re.escape(var)}\b', expr) is not None


def _plain(expr):
    return not re.search(rf'{IDENT}\s*\(', expr) and not re.search(r'(?<![=!<>])=(?!=)|\+\+|--', expr)


def _norm(expr):
    return re.sub(r'\s+', '', expr)


def _read(clean, source, at, types):
    """One table read starting at `at` (the start of a statement), or None.

    Returns (end, var, sym, index, kind, rest): `end` just past the statement (or the staged pair), `kind` one of
    'load', 'sum', 'element' with `rest` the offset text."""
    hit = re.compile(rf'({IDENT})\s*=\s*').match(clean, at)
    if not hit or hit[1] not in types:
        return None
    var, typ = hit[1], types[hit[1]]
    pos = hit.end()
    staged = re.compile(rf'\(\s*{re.escape(typ)}\s*\*\s*\)\s*&\s*({IDENT})\s*\[').match(clean, pos)
    amp = re.compile(rf'&\s*({IDENT})\s*\[').match(clean, pos)
    bare = re.compile(rf'({IDENT})\s*\[').match(clean, pos)
    head = staged or amp or bare
    if not head:
        return None
    sym = head[1]
    if sym == var or sym in types:
        return None
    open_at = head.end() - 1
    close = _bracket(clean, open_at)
    if close < 0:
        return None
    index = source[open_at + 1:close].strip()
    if _names(index, var) or not _plain(index):
        return None
    semi = clean.find(';', close)
    if semi < 0:
        return None
    tail = clean[close + 1:semi].strip()
    if staged:
        if tail:
            return None
        nxt = re.compile(r'\s*').match(clean, semi + 1).end()
        pair = re.compile(rf'{re.escape(var)}\s*=\s*([^;{{}}]*);').match(clean, nxt)
        if not pair:
            return None
        second = pair[1].strip()
        deref = rf'\*\s*\(\s*{re.escape(typ)}\s*\*\s*\*\s*\)\s*{re.escape(var)}'
        load = re.fullmatch(deref, second)
        summ = re.fullmatch(rf'{deref}\s*([+-].*)', second, re.S)
        elem = re.fullmatch(rf'&\s*\(\s*{deref}\s*\)\s*\[(.*)\]', second, re.S)
        if load:
            kind, rest = 'load', ''
        elif summ and not _names(summ[1], var) and _plain(summ[1]):
            kind, rest = 'sum', summ[1].strip()
        elif elem and not _names(elem[1], var) and _plain(elem[1]) and elem[1].count('[') == elem[1].count(']'):
            kind, rest = 'element', elem[1].strip()
        else:
            return None
        return pair.end(), var, sym, index, kind, rest
    if amp:
        element = re.fullmatch(r'\[(.*)\]', tail, re.S)
        if not element or _bracket(tail, 0) != len(tail) - 1 or _names(element[1], var) or not _plain(element[1]):
            return None
        return semi + 1, var, sym, index, 'element', source[close + 1:semi].strip()[1:-1].strip()
    if not tail:
        return semi + 1, var, sym, index, 'load', ''
    if re.fullmatch(r'[+-][^?:]*', tail) and not _names(tail[1:], var) and _plain(tail[1:]) \
            and tail.count('[') == tail.count(']'):
        return semi + 1, var, sym, index, 'sum', source[close + 1:semi].strip()
    return None


def _loop_top(clean, at, start):
    """Just past the `{` (and its line break) of the loop body that holds `at`, or -1 when it is not a loop's."""
    opening = c_scan.enclosing_block(clean, at, start)
    if opening < 0 or not c_scan.LOOP_HEADER.search(c_scan.header_before(clean, opening)):
        return -1
    return opening + 1 + re.match(r'[ \t]*\n?', clean[opening + 1:]).end()


def _fresh(word, taken):
    name, n = word, 2
    while name in taken:
        name, n = f'{word}{n}', n + 1
    taken.add(name)
    return name


def _cast(read, types, elements):
    """The cast a slot or table pointer of `read`'s local needs: none when the table's extern has its element type."""
    return '' if elements.get(read[2]) == types[read[1]] else f'({types[read[1]]} **) '


def _slot_line(read, hoist, table, slots, indent, types, elements):
    if read is hoist:
        return f'{indent}{slots[read[1]]} = &{table}[{read[3]}];\n'
    return f'{indent}{slots[read[1]]} = {_cast(read, types, elements)}&{read[2]}[{read[3]}];\n'


def _load_line(read, slots, indent):
    var, slot, kind, rest = read[1], slots[read[1]], read[4], read[5]
    if kind == 'load':
        return f'{indent}{var} = *{slot};\n'
    if kind == 'sum':
        return f'{indent}{var} = *{slot} {rest};\n'
    return f'{indent}{var} = &(*{slot})[{rest}];\n'


_DECL = re.compile(rf'[ \t]*(?:const[ \t]+)?{IDENT}(?:[ \t]*\*+[ \t]*|[ \t]+){IDENT}[ \t]*(?:\[[^\];\n]*\][ \t]*)*;[ \t]*\n')
_INIT = re.compile(rf'([ \t]*)((?:const[ \t]+)?{IDENT}(?:[ \t]*\*+[ \t]*|[ \t]+))({IDENT})[ \t]*=(?!=)[ \t]*([^;{{}}\n]*);[ \t]*\n')
_KEYWORDS = {'return', 'goto', 'else', 'case', 'do', 'while', 'for', 'if', 'switch'}


def _declaration(clean, at):
    """The end of the declaration line at `at` (bare, or `T *v = expr;` with `initialised`), or None."""
    for pattern, initialised in ((_DECL, False), (_INIT, True)):
        hit = pattern.match(clean, at)
        if hit and re.match(rf'[ \t]*(?:const[ \t]+)?({IDENT})', hit[0])[1] not in _KEYWORDS:
            return hit, initialised
    return None, False


def _declarations_end(clean, at):
    """Just past the declarations (and blank lines) that open the block whose body starts at `at`."""
    while True:
        blank = re.compile(r'[ \t]*\n').match(clean, at)
        if blank:
            at = blank.end()
            continue
        hit, _ = _declaration(clean, at)
        if not hit:
            return at
        at = hit.end()


def _split_initialisers(source, name):
    """`source` with each loop body's initialised declarations split into declarations and assignments, or None."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    start, end = span
    edits = []
    for brace in re.finditer(r'\{', clean[start:end]):
        opening = start + brace.start()
        if not c_scan.LOOP_HEADER.search(c_scan.header_before(clean, opening)):
            continue
        at = opening + 1 + re.match(r'[ \t]*\n?', clean[opening + 1:]).end()
        assigns, splits = [], []
        while True:
            blank = re.compile(r'[ \t]*\n').match(clean, at)
            if blank:
                at = blank.end()
                continue
            hit, initialised = _declaration(clean, at)
            if not hit:
                break
            if initialised:
                text = source[hit.start():hit.end()]
                part = _INIT.match(text)
                splits.append((hit.start(), hit.end(), f'{part[1]}{part[2].rstrip()}{"" if part[2].rstrip().endswith("*") else " "}{part[3]};\n'))
                assigns.append(f'{part[1]}{part[3]} = {part[4].strip()};\n')
            at = hit.end()
        if splits:
            edits.extend(splits)
            edits.append((at, at, ''.join(assigns)))
    if not edits:
        return None
    return _apply(source, edits)


def _apply(source, edits):
    """`source` with each (start, end, text) replaced; at one position, earlier edits in the list come first."""
    text = source
    for index, (lo, hi, new) in sorted(enumerate(edits), key=lambda item: (item[1][0], item[0]), reverse=True):
        text = text[:lo] + new + text[hi:]
    return text


def rewrites(source, name):
    result = _rewrites(source, name)
    split = _split_initialisers(source, name)
    if split:
        result += [text for text in _rewrites(split, name) if text not in result]
    return result[:LIMIT]


def _rewrites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    if re.search(r'\b(?:volatile|asm|__asm__)\b', clean[start:end]):
        return []
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    body = clean[opening:end]
    types, decl_end = {}, {}
    for hit in re.finditer(rf'(?m)^[ \t]*(?:const\s+)?({IDENT})\s*\*\s*({IDENT})\s*;[ \t]*\n', body):
        if hit[1] not in ('return', 'goto', 'else'):
            types.setdefault(hit[2], hit[1])
            decl_end.setdefault(hit[2], opening + hit.end())
    elements = {m[2]: m[1] for m in re.finditer(rf'\bextern\s+(?:const\s+)?({IDENT})\s*\*\s*({IDENT})\s*\[', clean)}
    taken = set(re.findall(IDENT, clean))
    result = []
    for line in re.finditer(r'(?m)^([ \t]*)(?=\S)', clean[opening:end]):
        at = opening + line.end()
        reads, pos = [], at
        while True:
            read = _read(clean, source, pos, types)
            if not read:
                break
            reads.append(read)
            pos = read[0]
            pos += re.match(r'[ \t]*\n[ \t]*', clean[pos:]).end() if re.match(r'[ \t]*\n', clean[pos:]) else 0
        if len(reads) < 2 or len({_norm(r[3]) for r in reads}) != 1 or len({r[1] for r in reads}) != len(reads) \
                or len({r[2] for r in reads}) != len(reads):
            continue
        if any(_names(r[3], other[1]) for r in reads for other in reads):
            continue
        top = _loop_top(clean, at, opening)
        if top < 0:
            continue
        top = min(_declarations_end(clean, top), at)
        indent = line[1]
        run_end = reads[-1][0]
        run_end += re.match(r'[ \t]*\n?', source[run_end:]).end()
        line_start = at - len(indent)
        top_indent = re.match(r'[ \t]*', source[top:]).group()
        first_decl = min(decl_end[r[1]] for r in reads)
        pad = re.match(r'[ \t]*', source[source.rfind('\n', 0, first_decl - 1) + 1:]).group()
        for hoist in reads:
            local = set(taken)
            table = _fresh(f'{hoist[1]}_table', local)
            slots = {r[1]: _fresh(f'{r[1]}_slot', local) for r in reads}
            table_line = f'{table} = {_cast(hoist, types, elements)}{hoist[2]};\n'
            decls = f'{pad}{types[hoist[1]]} **{table};\n' + ''.join(
                f'{pad}{types[r[1]]} **{slots[r[1]]};\n' for r in reads)
            for order in (reads, [hoist] + [r for r in reads if r is not hoist]):
                run = ''.join(_slot_line(r, hoist, table, slots, indent, types, elements) for r in order) \
                    + ''.join(_load_line(r, slots, indent) for r in order)
                for place in ('top', 'run'):
                    if place == 'run' or top == line_start:
                        edits = [(first_decl, first_decl, decls),
                                 (line_start, run_end, indent + table_line + run)]
                    else:
                        edits = [(first_decl, first_decl, decls), (top, top, top_indent + table_line),
                                 (line_start, run_end, run)]
                    text = _apply(source, edits)
                    if text != source and text not in result:
                        result.append(text)
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
