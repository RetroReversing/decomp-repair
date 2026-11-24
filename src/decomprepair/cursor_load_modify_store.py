"""A global cursor stepped as `p = G++;` across an intervening store: the cursor read, the store, then the step and the write-back.

The shape (SN GCC 2.8.1, `-G0 -mips3 -O2`; a record cursor of a display-list writer): after `cursor_record_postfix` a
cursor read and stepped in one expression follows a store of its own

    M2C_FIELD(arg0, s32 *, 0x10) = saved;
    p = G++;

and GCC's expansion of `G++` on a global reads G where the expression stands, steps the loaded register and stores it back
at once. The original read the cursor into a local before the store, stepped the local after it and wrote the result back:

    q = G;  M2C_FIELD(arg0, s32 *, 0x10) = saved;  p = q++;  G = q;

so the load of G sits above the store, the step and the write-back below it, and the write-back's register is the
stepped copy (the target has `lw rX, %lo(G)(...)` then a store, then `addiu rY, rX, K` and `sw rY, %lo(G)(...)`).

The gate is the target's: a load of the global's symbol, a store to some other address, and a store back to the
global's symbol, in that order. Nothing is proposed without the assembly.

`variants` finds a statement `p = G++;` (`G` a global declared `extern T G;` in the file or the header) preceded by one or
two plain store statements (no call, no mention of G, each an assignment to a local, another global, or an `M2C_FIELD`).
Children, one per count of statements the read is hoisted above (1, then 2):

- `cursor_load_modify_store`: `q = G;` above those stores and `p = q++;` followed by `G = q;` in place of `p = G++;`
  (`q` a new local of the global's type).

Faithful under the same assumption the target makes: the intervening stores do not change the cursor global (they name
neither it nor anything of its type that is not a plain local, a different global or a record field). At most LIMIT
children; this module reads text only and never compiles or judges."""
import re

from .hand_found_support import (
    IDENT,
    LOADS,
    RELOCATED,
    STORES,
    blocks,
    calls_in,
    declare,
    declaring,
    fresh,
    instructions,
    mentions_of,
    simple,
    stmts,
    store_target,
)
from .integer_repair_support import edit, view

FAMILY = 'cursor_load_modify_store'
FAMILIES = (FAMILY,)
LIMIT = 4
MAX_HOIST = 2


def evidence(asm):
    """{symbol} of globals the target loads, stores something else past, and stores back to, in that order."""
    ops = instructions(asm)
    found = set()
    loaded = {}
    for index, (op, args) in enumerate(ops):
        if len(args) != 2:
            continue
        hit = RELOCATED.search(args[1])
        if op in LOADS and hit:
            loaded.setdefault(hit['symbol'], index)
        if op in STORES:
            symbol = hit['symbol'] if hit else None
            if symbol in loaded and any(o in STORES and len(a) == 2 and not _same(a[1], symbol) for o, a in ops[loaded[symbol] + 1:index]):
                found.add(symbol)
    return found


def _same(operand, symbol):
    hit = RELOCATED.search(operand)
    return bool(hit and hit['symbol'] == symbol)


def _plain_store(text, g):
    """True for a plain store statement that cannot change the global `g`."""
    if not simple(text) or calls_in(text) or mentions_of(text, g):
        return False
    stored = store_target(text)
    return bool(stored) and (re.fullmatch(IDENT, stored[0]) is not None or stored[0].lstrip().startswith('M2C_FIELD('))


def variants(source, name, header='', arch='mips', asm=''):
    if arch != 'mips':
        return []
    wanted = evidence(asm)
    part = view(source, name) if wanted else None
    if not part:
        return []
    clean = part.clean
    taken = set(re.findall(IDENT, source)) | set(re.findall(IDENT, header or ''))
    children = []
    for lo, hi in blocks(part):
        spans = stmts(part, lo, hi)
        for index, (start, end) in enumerate(spans):
            hit = re.fullmatch(rf'(?P<p>{IDENT})\s*=\s*(?P<g>{IDENT})\s*\+\+\s*;', clean[start:end].strip())
            if not hit or hit['g'] not in wanted or hit['p'] == hit['g']:
                continue
            declared = re.search(rf'(?m)^[ \t]*extern\s+(?P<type>[^;()]+?)\s*\b{re.escape(hit["g"])}\s*;', clean[:part.opening] + '\n' + _blank_header(header))
            if not declared or re.search(r'[\[\]]', declared['type']):
                continue
            q = fresh(hit['g'], taken, 'q')
            declaration = declare(source, part, [declaring(declared['type'], q)])
            if not declaration:
                continue
            for count in range(1, MAX_HOIST + 1):
                if index - count < 0:
                    break
                above = [clean[a:b] for a, b in spans[index - count:index]]
                if not all(_plain_store(text, hit['g']) for text in above):
                    break
                first = spans[index - count][0]
                indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, first) + 1:])[0]
                here = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0]
                text = f'{hit["p"]} = {q}++;\n{here}{hit["g"]} = {q};'
                children.append((FAMILY, edit(source, [declaration, (first, first, f'{q} = {hit["g"]};\n{indent}'), (start, end, text)])))
    return list(dict.fromkeys(children))[:LIMIT]


def _blank_header(header):
    return re.sub(r'/\*.*?\*/|//[^\n]*', ' ', header or '', flags=re.S)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'arch', 'asm'),
          'order': 69, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
