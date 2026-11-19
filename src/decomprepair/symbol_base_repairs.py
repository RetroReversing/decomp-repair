"""A symbol's address held in a local pointer, as the game's C read it, where m2c named the symbol at every use.

Named directly, gcc folds the symbol's `%lo` into each access: `lbu $v0, %lo(D)($at)`. Where the source read the table
through a pointer, the address is built once (`lui`/`addiu`) and the accesses go through that register. N64 functions
of a KMC GCC game did that and were 52-65% from m2c's drafts; with the address in a pointer set where it is first
needed, they were exact:

    var_v0 = (temp_v1 * 4) + D_800E4290;      ->   base = (s32 *) D_800E4290;
                                                   var_v0 = base + temp_v1;

The pointer is offered set just before the statement that first uses the symbol (set at the top of the function one
of them was 54% again: the register then lives across everything before) and at the top. A scalar whose address is
taken (`&D`), or that is named more than once (read, then cleared after a call), is read and written through the
pointer too: N64 functions kept such a global's address in a saved register across the call. A global pointer whose
fields are read is also offered with only its own tests and stores through the pointer. A step on the pointer is offered as the draft wrote it and, for a
wider type, divided by its size (`&D - 0x20` on an `s16`: the game stepped 0x20 bytes).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'symbol_address_local'
FAMILIES = (FAMILY,)
SIZES = {'char': 1, 's8': 1, 'u8': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4,
         'float': 4, 'long': 4}

IDENT = r'[A-Za-z_]\w*'
ARRAY = re.compile(r'(?m)^[ \t]*extern\s+(?P<type>(?:unsigned\s+|signed\s+)?' + IDENT + r')\s+(?P<name>' + IDENT
                   + r')\s*\[\s*\]\s*;')
SCALAR = re.compile(r'(?m)^[ \t]*extern\s+(?P<type>(?:unsigned\s+|signed\s+)?' + IDENT + r'(?:\s*\*)*)\s*(?<![\w])'
                    r'(?P<name>' + IDENT + r')\s*;')


def _statement_start(body, at):
    depth, start = 0, 1
    for i, ch in enumerate(body[:at]):
        depth += (ch == '(') - (ch == ')')
        if depth == 0 and ch in ';{}':
            start = i + 1
    return start


def _reads_through(body, use):
    """Whether this use of a pointer-valued scalar only reads through it: `M2C_FIELD(D, ...)`, `D->f`, `*D`, `D[i]`."""
    if use['amp']:
        return False
    before, after = body[:use.start()], body[use.end():]
    return bool(re.search(r'\bM2C_FIELD\s*\(\s*$', before) or re.match(r'\s*(?:->|\[)', after)
                or re.search(r'(?<![\w)\]])\*\s*$', before))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    outside = clean[:span[0]] + clean[span[1]:]
    body = clean[opening:end]
    symbols = [(m['name'], m['type'], True) for m in ARRAY.finditer(outside)]
    symbols += [(m['name'], m['type'], False) for m in SCALAR.finditer(outside)
                if m['type'] not in ('struct', 'union', 'enum')]
    result = []
    for symbol, kind, array in symbols:
        uses = list(re.finditer(r'(?<![\w.>])(?P<amp>&\s*)?' + re.escape(symbol) + r'\b(?!\s*\()', body))
        if not uses:
            continue
        if array:
            # an address in arithmetic (`D + i`, `i + D`), never an index (`D[i]`, which gcc folds the same either way)
            if any(re.match(r'\s*\[', body[m.end():]) for m in uses):
                continue
            if not any(re.search(r'[+-]\s*$', body[:m.start()]) or re.match(r'\s*[+-]', body[m.end():]) for m in uses):
                continue
        elif not any(m['amp'] for m in uses) and len(uses) < 2:
            continue  # a scalar named once: nothing to share
        local = '__base_' + symbol
        kind = ' '.join(kind.replace('*', ' * ').split()).replace('* *', '**')
        pointer = f'{kind} *' if not kind.endswith('*') else f'{kind}*'
        address = symbol if array else '&' + symbol
        first = _statement_start(body, uses[0].start())
        indent = re.match(r'\s*', body[first:])[0].split('\n')[-1] or '    '
        size = SIZES.get(kind.split()[-1], 1)
        steps = [None] + ([size] if size > 1 else [])
        # (a global pointer tested and cleared through its address while its fields are read through the value: an N64
        # function was exact only with `M2C_FIELD(D, ...)` left naming the global, gcc reloading it with %hi/%lo)
        through = [_reads_through(body, m) for m in uses]
        keeps = (False, True) if not array and any(through) and not all(through) else (False,)
        for placement, scale, keep in [(p, k, e) for p in ('use', 'top') for k in steps for e in keeps]:
            text = source
            # replacements back to front so the offsets stay valid
            for m, inner in reversed(list(zip(uses, through))):
                if keep and inner:
                    continue
                at = opening + m.start()
                if array or m['amp']:
                    new = local
                else:
                    new = f'(*{local})'
                stop = opening + m.end()
                step = re.match(r'\s*([+-])\s*(0[xX][0-9a-fA-F]+|\d+)\b', clean[stop:]) if scale else None
                if step and int(step[2], 0) % scale == 0:
                    # (the draft's number counted bytes where the pointer counts elements)
                    new += f' {step[1]} 0x{int(step[2], 0) // scale:X}'
                    stop += step.end()
                text = text[:at] + new + text[stop:]
            set_line = f'{local} = {address};\n'
            if placement == 'use':
                at = opening + first + len(re.match(r'\s*', body[first:])[0])
                text = text[:at] + set_line + indent + text[at:]
                text = text[:opening + 1] + f'\n    {pointer}{local};' + text[opening + 1:]
            else:
                declarations = re.match(r'\{(?:\s*(?:register\s+)?[\w ]+?[\s*]+' + IDENT + r'(?:\s*\[[^]]*\])?\s*;)*', body)
                at = opening + declarations.end()
                text = text[:at] + f'\n    {pointer}{local};\n\n    {set_line.rstrip()}' + text[at:]
                text = text[:opening + 1] + text[opening + 1:]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
        if len(result) >= 8:
            break
    return result
