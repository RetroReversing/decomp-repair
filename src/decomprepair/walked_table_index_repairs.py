"""A table walked by a byte cursor, its shared offset local and a void tail: written back as the game's indexed loop.

m2c turns a short `for (i = 0; i < N; i++)` over parallel global tables into a counter, a `char *` cursor over the
first table (stepped by the table's element size) and one offset local `temp = counter * 4` that every other table's
read shares:

    var_s1 = 0;
    var_s2 = &D_A;
    do {
        temp_a0 = ...;
        temp_s0 = var_s1 * 4;
        if (x == *(s32 *)var_s2 && y == *(s32 *)(D_B + temp_s0)) { ... }
        var_s2 += 4;
        var_s1 += 1;
    } while (var_s1 < 2U);
    ...
    if ((u8)temp_s0 == 0) {
        func();
    }

and gcc 2.7.2 (KMC, `-O2`) builds that with the cursor set up *before* the constants the loop pass hoists, with the
shared offset reduced to the counter's own byte offset, and a masking `andi` on the tail's test. The game's loop reads
the first table as `*(s32 *)(&D_A + var_s1)` (the loop pass then derives that address after the hoisted constants and
keeps the counter), spells the offset at each use (`D_B + var_s1 * 4`, so cse has no shared offset to reduce), and the
function returned the callee's result: `v = func();` under a plain `v == 0` with `return v;`.

None of the three alone helps (measured on one 108-instruction function, gcc-2.7.2-kmc `-G0 -mips3 -mgp32 -mfp32 -O2`,
from 100: the indexed read alone 2083, the inlined offset alone 2287, the returned tail alone 720; the first two
together 400; all three 0). So one child makes every edit that applies.

The loop edits are offered only when the meaning is unchanged: the counter starts at 0 and steps by one, the cursor
starts at a scalar global's address and steps by that scalar's size, every read is `*(T *)cursor` with T the scalar's
size, nothing reads the cursor after the loop, and the offset local is assigned (never read) before the code that
follows the loop uses it again. The tail edit needs a `void` function, no `return`, a callee declared to return an
integer, and the local tested as `(u8)local == 0`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'walked_table_index'
FAMILIES = (FAMILY,)

ID = r'[A-Za-z_]\w*'
SCALAR_SIZE = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4}
NUMBER = re.compile(r'\(?\s*(?:\(\s*(?:u32|s32|unsigned(?:\s+int)?|int)\s*\)\s*)?(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*\)?')


def _norm(t):
    return re.sub(r'\s+', ' ', re.sub(r'\b(?:extern|static|const|volatile)\b', ' ', t)).replace(' *', '*').strip()


def _decl(text, ident, tail=''):
    for m in re.finditer(rf'^[ \t]*([A-Za-z_][\w \t\*]*?)\b{re.escape(ident)}\s*{tail}\s*;[ \t]*\n?', text, re.M):
        return m
    return None


def _offset_local(inner_clean, counter, after):
    """(definition span in `inner_clean`, local, scale text) of `local = counter * K;` whose uses can be inlined."""
    for m in re.finditer(rf'^[ \t]*({ID})\s*=\s*{re.escape(counter)}\s*(\*\s*(?:0[xX][0-9a-fA-F]+|\d+)|<<\s*\d+)\s*;[ \t]*\n?',
                         inner_clean, re.M):
        local = m[1]
        if local == counter or re.search(rf'\b{re.escape(local)}\b\s*(?:[-+*/%|&^]|<<|>>)?=(?!=)', inner_clean[m.end():]):
            continue
        if re.search(rf'\b{re.escape(local)}\b', inner_clean[:m.start()]):
            continue
        nxt = re.search(rf'\b{re.escape(local)}\b', after)
        if nxt and not re.match(r'\s*=(?!=)', after[nxt.end():]):
            continue  # (read again after the loop with the loop's last value)
        return m, local, m[2]
    return None


def _loop_edits(source, clean, a, b):
    """[(start, end, text)] edits of the walk in the function `source[a:b]`, or None."""
    for do in re.finditer(r'\bdo\s*{', clean[a:b]):
        opening = a + do.end() - 1
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        tail = re.match(r'\s*while\s*\(\s*(' + ID + r')\s*<\s*([^;]+?)\s*\)\s*;', clean[end:b])
        bound = NUMBER.fullmatch(tail[2].strip()) if tail else None
        if not bound or not re.search(r'[1-9a-fA-F]', bound[1]):
            continue
        counter, loop_end = tail[1], end + tail.end()
        before = clean[a:a + do.start()]
        zero = rf'{re.escape(counter)}\s*=\s*0\s*;'
        walk = rf'({ID})\s*=\s*&\s*({ID})\s*;'
        init = re.search(rf'[ \t]*{zero}[ \t]*\n?[ \t]*{walk}[ \t]*\n?[ \t]*$', before)
        init = init or re.search(rf'[ \t]*{walk}[ \t]*\n?[ \t]*{zero}[ \t]*\n?[ \t]*$', before)
        if not init:
            continue
        cursor, glob = init[1], init[2]
        gdecl, cdecl = _decl(source[:a], glob), _decl(source[a:b], cursor)
        kind = _norm(gdecl[1]) if gdecl else ''
        if kind not in SCALAR_SIZE or not cdecl or not re.fullmatch(r'(?:s8|u8|char)\*', _norm(cdecl[1])) or cursor == counter:
            continue
        size = SCALAR_SIZE[kind]
        body = clean[opening + 1:end - 1]
        steps = re.search(rf'[ \t]*(?:{re.escape(cursor)}\s*\+=\s*{size}\s*;\s*{re.escape(counter)}\s*\+=\s*1\s*;'
                          rf'|{re.escape(counter)}\s*\+=\s*1\s*;\s*{re.escape(cursor)}\s*\+=\s*{size}\s*;)[ \t]*\n[ \t]*$', body)
        if not steps:
            continue
        inner = body[:steps.start()]
        labels = set(re.findall(rf'^[ \t]*({ID})\s*:(?!:)', inner, re.M))
        if (re.search(r'\b(?:continue|break)\b', inner)
                or any(target not in labels for target in re.findall(rf'\bgoto\s+({ID})', inner))
                or re.search(rf'\b{re.escape(counter)}\s*(?:(?:[-+*/%|&^]|<<|>>)?=(?!=)|\+\+|--)', inner)
                or re.search(rf'(?:&|\+\+|--)\s*\b{re.escape(counter)}\b', clean[a:end])
                or re.search(rf'\b{re.escape(cursor)}\b', clean[loop_end:b])
                or len(re.findall(rf'\b{re.escape(glob)}\b', clean[a:b])) != 1
                or len(re.findall(rf'\b{re.escape(cursor)}\b', clean[a:b])) != len(re.findall(rf'\b{re.escape(cursor)}\b', inner)) + 3):
            continue  # (the cursor: its declaration, its init, its step, its reads, and nothing else)
        read = re.compile(rf'\*\s*\(\s*{re.escape(kind)}\s*\*\s*\)\s*{re.escape(cursor)}\b(?!\s*[\[+\-])')
        reads = list(read.finditer(inner))
        if not reads or len(reads) != len(re.findall(rf'\b{re.escape(cursor)}\b', inner)):
            continue
        base = opening + 1
        edits = [(base + r.start(), base + r.end(), f'*({kind} *)(&{glob} + {counter})') for r in reads]
        offset = _offset_local(inner, counter, clean[loop_end:b])
        if offset:
            m, local, scale = offset
            edits.append((base + m.start(), base + m.end(), ''))
            scaled = re.sub(r'\s+', ' ', scale)
            edits += [(base + m.end() + u.start(), base + m.end() + u.end(), f'({counter} {scaled})')
                      for u in re.finditer(rf'\b{re.escape(local)}\b', inner[m.end():])]
        step_cut = re.search(rf'[ \t]*{re.escape(cursor)}\s*\+=\s*{size}\s*;[ \t]*\n', body[steps.start():steps.end()])
        edits.append((base + steps.start() + step_cut.start(), base + steps.start() + step_cut.end(), ''))
        cut = re.search(rf'[ \t]*{walk}[ \t]*\n?', init.group(0))
        edits.append((a + init.start() + cut.start(), a + init.start() + cut.end(), ''))
        edits.append((a + cdecl.start(), a + cdecl.end(), ''))
        return edits
    return None


def _tail_edits(source, clean, a, b):
    """[(start, end, text)] making a void function's last `if ((u8)v == 0) { call(); }` return the call's result."""
    head = re.match(r'void(?=\s+' + ID + r'\s*\([^)]*\)\s*{)', clean[a:b])
    if not head or re.search(r'\breturn\b', clean[a:b]):
        return None
    last = None
    for m in re.finditer(rf'\bif\s*\(\s*\(\s*u8\s*\)\s*({ID})\s*==\s*0\s*\)\s*{{\s*({ID})\s*\(([^;{{}}]*)\)\s*;\s*}}\s*(?=}}\s*$)',
                         clean[a:b]):
        last = m
    if not last:
        return None
    local, callee = last[1], last[2]
    decl = _decl(source[a:b], local)
    if not decl or _norm(decl[1]) not in ('s32', 'u32', 'int') or not re.search(
            rf'^[ \t]*(?:extern\s+)?(?:s32|int)\s+{re.escape(callee)}\s*\(', clean[:a], re.M):
        return None
    start = a + last.start()
    stop = a + last.end()
    call = re.search(rf'{re.escape(callee)}\s*\(', clean[start:stop])
    cast = re.search(rf'\(\s*u8\s*\)\s*{re.escape(local)}', clean[start:stop])
    final = clean.rfind('}', a, b)
    line = source.rfind('\n', 0, start) + 1
    indent = re.match(r'[ \t]*', source[line:]).group()
    return [(a, a + 4, 's32'),
            (start + cast.start(), start + cast.end(), local),
            (start + call.start(), start + call.start(), f'{local} = '),
            (final, final, f'{indent}return {local};\n')]


def _apply(source, edits):
    for start, end, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    a, b = span
    clean = _blank(source)
    loop, tail = _loop_edits(source, clean, a, b), _tail_edits(source, clean, a, b)
    out = []
    for edits in ((loop or []) + (tail or []), loop, tail):
        if edits:
            text = _apply(source, edits)
            if text != source and (FAMILY, text) not in out:
                out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 75}  # the registry: no caller wiring (registry.py)
