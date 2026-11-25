"""A loop bound that is a global read, held in a local set above the loop.

`for (i = 0; i < D_8000; i++)` reads the global at every test; when the body has no call and writes nothing the compiler
may keep the global in memory (a `lw` at each pass) while a developer's `n = D_8000;` above the loop is a pseudo that is
loaded once into a saved register and compared with `slt`. Mined from the permuter-gap notes of matched functions: a loop
whose bound the target loads once into a saved register (`lw` before the loop, `sltu` against that register inside it)
needed that rewrite, and the families that hold a literal bound (`constant_in_local_bound`) or a pointer (`table_base_local`)
did not offer it.

`loop_bound_global_local`: a `for` or `while` whose test compares a counter with a scalar global declared in the header
(`extern T D_x;`, T a scalar type) is written with `n = D_x;` on the line above the loop (above its `do` for a do-while)
and the test reading `n`, `n` declared after the leading declarations with the global's type. Only when the loop body has
no call (a call may change the global) and no assignment to the global. At most `LIMIT` children, in the source's order.
A function with `volatile`, `asm`, `goto` or a preprocessor line is left alone. Proposals only; the byte judge decides."""
import re

from .constant_in_local import _loops
from .integer_repair_support import IDENT, edit, view
from .local_split_reuse import _CALL, _insert_declaration

FAMILY = 'loop_bound_global_local'
FAMILIES = (FAMILY,)
LIMIT = 4
_SCALAR = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'f32', 'int', 'char', 'short', 'long', 'float', 'unsigned', 's64', 'u64'}
_TEST = re.compile(rf'(?P<a>{IDENT})\s*(?P<op><=?|!=|>=?)\s*(?P<g>D_\w+)\Z|(?P<g2>D_\w+)\s*(?P<op2>>=?|<=?)\s*(?P<a2>{IDENT})\Z')


def _global_types(header):
    return {m['name']: m['type'].strip() for m in re.finditer(
        rf'(?m)^\s*extern\s+(?P<type>(?:(?:const|unsigned|signed)\s+)*{IDENT})\s+(?P<name>D_\w+)\s*;', header)
        if m['type'].split()[-1] in _SCALAR}


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    if re.search(r'\b(?:volatile|asm|__asm__|goto)\b|^\s*#', clean[part.opening:part.end], re.M):
        return []
    types = _global_types(header + '\n' + source)
    used = set(re.findall(IDENT, clean[part.opening:part.end]))
    out = []
    for loop, lo, hi in _loops(clean, part.opening + 1, part.end):
        header_text = clean[lo:hi]
        test = header_text.split(';')[1] if loop['kind'] == 'for' and header_text.count(';') >= 2 else header_text
        base = lo + (header_text.index(test) if loop['kind'] == 'for' else 0)
        match = _TEST.fullmatch(test.strip())
        if not match:
            continue
        glob = match['g'] or match['g2']
        if glob not in types:
            continue
        # the loop's body: from the closing parenthesis to the matching brace
        opening = clean.find('{', hi)
        if opening < 0 or clean[hi + 1:opening].strip():
            continue
        depth, end = 0, opening
        while end < part.end:
            depth += {'{': 1, '}': -1}.get(clean[end], 0)
            if depth == 0:
                break
            end += 1
        inside = clean[opening:end + 1]
        if _CALL.search(inside) or re.search(rf'\b{re.escape(glob)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', inside):
            continue
        local = f'n_{glob[2:].lower()}'
        if local in used:
            continue
        at = loop.start()
        line = source.rfind('\n', 0, at) + 1
        if source[line:at].strip():
            continue
        if loop['kind'] == 'while' and clean[hi + 1:].lstrip().startswith(';'):
            continue
        indent = re.match(r'[ \t]*', source[line:at])[0]
        child = edit(source, [(base + test.index(glob), base + test.index(glob) + len(glob), local),
                              (line, line, f'{indent}{local} = {glob};\n')])
        moved = view(child, name)
        if moved:
            kind = types[glob]
            out.append((FAMILY, _insert_declaration(child, moved, f'{kind} {local};')))
            used.add(local)
    return list(dict.fromkeys(item for item in out if item[1] != source))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
