"""A `for` loop that steps pointers started just before it, written as the guarded `do { } while` the game's code
compiled to (GCC 2.7.2, KMC, N64).

    f32 *y = (f32 *)((u8 *) &table + 4);  f32 *x = &table;
    for (i = 0; i < n; y += 9, i++, x += 9) { ... }

starts the two pointers before the loop's test: jump.c copies the test in front of the loop and the pointers' starts
come first, `lui; addiu` pairs then the `blez`. In the target of a 529-instruction function the test came first and the
pointers were started after it (`blez $s3,..; move $s0,$zero; lui $t1,..; addiu $t1,..; addiu $a0,$t1,4; lui $v1,..`):
the guard `i = 0; if (i < n)` holds the starts, the body is a `do { ... y += 9; i++; x += 9; } while (i < n);`, and
the instruction order is that of the game (120 -> 0; every row but the entry's order was already right). The steps keep
the order of the `for`'s third clause, after the body.

Offered for a braced `for (c = 0; cond; steps)` whose steps are `v += K`, `v++` or `++v`, preceded by the declarations,
each with an initialiser, of the pointers it steps, when the body has no `continue`, `goto` or label. A candidate
rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'guarded_cursor_do_loop'
FAMILIES = (FAMILY,)
_FOR = re.compile(r'\bfor\s*\(')
_STEP = re.compile(rf'(?:(?P<a>{IDENT})\s*(?:\+\+|\+=\s*{NUMBER})|\+\+\s*(?P<b>{IDENT}))$')
_DECL = re.compile(rf'(?m)^(?P<lead>[ \t]*)(?P<type>(?:\w+[ \t]+)+\**[ \t]*)(?P<v>{IDENT})[ \t]*=[ \t]*(?P<init>[^;\n]+);[ \t]*\n')


def _split(text):
    parts, depth, start = [], 0, 0
    for at, char in enumerate(text):
        depth += (char in '([{') - (char in ')]}')
        if char == ',' and depth == 0:
            parts.append(text[start:at].strip())
            start = at + 1
    parts.append(text[start:].strip())
    return parts


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _FOR.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        if not shut:
            continue
        pieces = clean[hit.end():shut - 1].split(';')
        if len(pieces) != 3:
            continue
        init = re.fullmatch(rf'\s*(?P<c>{IDENT})\s*=\s*0\s*', pieces[0])
        steps = _split(pieces[2])
        stepped = [(_STEP.match(s)) for s in steps]
        if not init or not all(stepped) or len(steps) < 2:
            continue
        counter = init['c']
        names = [m['a'] or m['b'] for m in stepped]
        if counter not in names or len(set(names)) != len(names):
            continue
        cond = pieces[1].strip()
        body_open = re.match(r'\s*\{', clean[shut:])
        if not cond or not body_open:
            continue
        open_at = shut + body_open.end() - 1
        end = close(clean, open_at, '{', '}')
        if not end or re.search(r'\b(?:continue|goto)\b|^\s*\w+\s*:(?!:)', clean[open_at:end], re.M):
            continue
        # the declarations just before the loop that start the stepped pointers
        before = clean[:hit.start()]
        starts, at = [], len(before.rstrip(' \t'))
        for decl in reversed(list(_DECL.finditer(before, part.opening + 1))):
            if decl.end() != at:
                break
            starts.append(decl)
            at = decl.start()
        starts.reverse()
        cursors = {d['v'] for d in starts}
        if not starts or cursors != set(names) - {counter}:
            continue
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start()) + 1:])[0]
        edits = []
        assigns = ''
        for decl in starts:
            kind = decl['type'].rstrip()
            edits.append((decl.start(), decl.end(), f"{decl['lead']}{kind}{'' if kind.endswith('*') else ' '}{decl['v']};\n"))
            assigns += f"{indent}  {decl['v']} = {source[decl.start('init'):decl.end('init')].strip()};\n"
        test = source[hit.end() + len(pieces[0]) + 1:hit.end() + len(pieces[0]) + 1 + len(pieces[1])].strip()
        step_text = ' '.join(f'{s};' for s in (source[hit.end() + len(pieces[0]) + len(pieces[1]) + 2:shut - 1].split(',')) for s in [s.strip()])
        edits.append((hit.start(), open_at + 1,
                      f'{counter} = 0;\n{indent}if ({test})\n{indent}{{\n{assigns}{indent}  do\n{indent}  {{'))
        edits.append((end - 1, end, f'{indent}  {step_text}\n{indent}  }} while ({test});\n{indent}}}'))
        out.append((FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
