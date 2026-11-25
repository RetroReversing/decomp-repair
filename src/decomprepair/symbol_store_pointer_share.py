"""A store into a global table inside a loop (`T[idx] = v;`) whose address the loop pass hoists, written through a
pointer local that the function also reads the table through elsewhere (`tp = T; tp[idx] = v;` .. `tp = T; .. tp[0]`).

On a 629-instruction N64 level loader (SN64 GCC 2.8.1, `sn-n64-281 -G0 -mips3 -O2 ... -mfp32`) a loop's arm stores a
count with `D_tab[idx] = cnt;` and the target builds the address in place (`lui $v1; addiu $v1; sll $v0, idx, 2;
addu $v0, $v0, $v1; sw`). loop.c moves the table's `high`/`lo_sum` pair to the preheader (`threshold * savings *
lifetime >= insn_count`: the pair's savings and lifetimes add up) and the spilled copy is rematerialised through
`$t1`, which swaps every later reload register. A pointer local set to the table in the same block is a movable too
(`reg_in_basic_block_p`), and `&T[idx]` in a pointer expands the shift first. A pointer *user variable* that is also
used in another block of the function, set in a part of the loop that may not run, is never moved
(`scan_loop`: a user variable set where `maybe_never` holds must be used only in its own basic block), so only the
lone `high` remains movable and is not worth moving: the address is built in place, in the target's order and
registers (15 rows -> 0, the last differences of the match). The pointer read of the table elsewhere is the same program.

symbol_store_pointer_share
    In a `for`/`while` loop, a statement `SYM[index] = value;` on its own line, SYM an `extern TYPE SYM[..]` table
    (source or header) that the function also indexes in another statement on its own line: a new local `TYPE *SYM_p`
    is set to SYM before both statements and both index it. One child per other statement.

Hypothesis from that match (loop.c's `scan_loop` and `move_movables`); the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'symbol_store_pointer_share'
FAMILIES = (FAMILY,)
LIMIT = 6
_EXTERN = re.compile(rf'(?m)^\s*extern\s+(?P<type>(?:(?:const|volatile|unsigned|signed|struct)\s+)*{IDENT}[\s*]*?)'
                     rf'\s*(?P<name>{IDENT})\s*\[[^\];]*\]\s*;')
_KEYWORDS = {'if', 'else', 'for', 'while', 'do', 'return', 'switch', 'case', 'sizeof', 'goto', 'break', 'continue'}


def _tables(text):
    return {m['name']: m['type'].strip() for m in _EXTERN.finditer(text)}


def _loops(clean, lo, hi):
    for hit in re.finditer(r'\b(?:for|while)\s*\(', clean[:hi]):
        if hit.start() < lo:
            continue
        after = close(clean, hit.end() - 1)
        brace = after and re.match(r'\s*{', clean[after:hi])
        if not brace:
            continue
        opening = after + brace.end() - 1
        end = close(clean, opening, '{', '}')
        if end:
            yield opening, end


def _line_start(clean, at):
    """The start of `at`'s line when the line opens a statement (else None)."""
    line = clean.rfind('\n', 0, at) + 1
    before = clean[:line].rstrip()
    if before[-1:] not in (';', '{', '}') or re.match(r'\s*(?:else|case|default)\b', clean[line:]):
        return None
    return line


def _declaration_end(clean, part):
    at = part.opening + 1
    decl = re.compile(rf'\s*(?:(?:const|register|static|struct|union|unsigned|signed)\s+)*{IDENT}[\s*]+{IDENT}'
                      r'(?:\s*\[[^\];]*\])?(?:\s*=[^;{}]*)?\s*;[ \t]*')
    while True:
        hit = decl.match(clean, at, part.end)
        if not hit or hit[0].split()[0] in _KEYWORDS:
            return at
        at = hit.end()


def _fresh(source, base):
    name, n = f'{base}_p', 1
    while re.search(rf'\b{name}\b', source):
        n += 1
        name = f'{base}_p{n}'
    return name


def _sites(source, header, part):
    clean = part.clean
    tables = _tables(header + '\n' + clean[:part.opening])
    loops = list(_loops(clean, part.opening, part.end))
    sites = []
    for sym, kind in tables.items():
        uses = [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(sym)}\s*\[', clean[part.opening:part.end])]
        uses = [part.opening + u for u in uses]
        if len(uses) < 2:
            continue
        for at in uses:
            if not any(lo < at < hi for lo, hi in loops):
                continue
            line = _line_start(clean, at)
            if line is None or clean[line:at].strip():
                continue
            bracket = clean.index('[', at)
            after = close(clean, bracket, '[', ']')
            store = after and re.match(r'\s*=(?!=)[^;{}]*;', clean[after:part.end])
            if not store:
                continue
            for other in uses:
                if other == at:
                    continue
                other_line = _line_start(clean, other)
                if other_line is None or other_line == line:
                    continue
                sites.append((sym, kind, line, at, other_line, other))
    return sites


def _child(source, part, site):
    sym, kind, line, at, other_line, other = site
    name = _fresh(source, sym)
    edits = []
    for start, use in ((line, at), (other_line, other)):
        indent = re.match(r'[ \t]*', source[start:])[0]
        edits.append((start, start, f'{indent}{name} = {sym};\n'))
        edits.append((use, use + len(sym), name))
    at = _declaration_end(part.clean, part)
    pad = re.search(r'\n([ \t]*)\S', source[part.opening:at + 1] + '\n    x')
    star = '' if kind.endswith('*') else ' '
    edits.append((at, at, f'\n{pad[1] if pad else "    "}{kind}{star}*{name};'))
    return edit(source, edits)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    return [(FAMILY, _child(source, part, site)) for site in _sites(source, header or '', part)[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
