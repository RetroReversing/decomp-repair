"""m2c's copy of a loop's entry value, written back as the `while` that reads the value where it uses it.

m2c spells a `while` whose condition reads memory as a guard over a `do`, keeping the value it read for the body:

    t = E;
    v = t;
    if (t != Z) {
        k = i * 0x8F0;
        do { USE(v); p += 16; v = E; } while (v != Z);
    }

The game wrote `while (E != Z) { USE(E); p += 16; }`. jump.c copies that loop's test in front of it, and the copy
tests its own constant (the entry and the bottom test then hold two registers for the same value, one hoisted out of the
outer loop and one in the inner loop's preheader), which the guard and the do-while, one expression each, never do.

On a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O1`) proximity scan over records and track points, the last three steps
of the machine draft's chain: 450 -> 0 with the `while` and the preheader's offset local written where it is read.

Offered for `t = E; [v = t;] if (t != Z) { [x = expr;]... do { BODY v = E; } while (v != Z); }` (also `v = E;
if (v != Z)`), where E is a read with no call (`M2C_FIELD` counts as a read), `Z` a literal or `NULL`, `t` is used
nowhere else, `v` only in the loop, and every use of `v` in BODY comes before any call and before any assignment to a
name E reads. The exact judge decides; one child keeps the preheader statements ahead of the loop, one writes each of
those locals (assigned once, no call) where it is read.

entry_value_while
    The rewrite above.
"""
import re

from .c_scan import close
from .integer_repair_support import IDENT, edit, view

FAMILY = 'entry_value_while'
FAMILIES = (FAMILY,)
LIMIT = 4
_ZERO = r'(?:NULL|0x[0-9A-Fa-f]+|-?\d+(?:\.\d+)?[fFuUlL]*)'
_GUARD = re.compile(rf'\bif\s*\(\s*(?P<g>{IDENT})\s*!=\s*(?P<z>{_ZERO})\s*\)\s*\{{')
_ASSIGN = re.compile(rf'\s*(?P<name>{IDENT})\s*=\s*(?P<value>[^;{{}}=]+);')
_READS = {'M2C_FIELD', 'sizeof'}
_CALL = re.compile(rf'({IDENT})\s*\(')
_TYPE_WORDS = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'f32', 'f64', 'int', 'char', 'short', 'float', 'void', 'unsigned',
               'signed', 'long'}


def _pure(text):
    """No call, increment or assignment (casts and `M2C_FIELD` are not calls)."""
    if re.search(r'\+\+|--|(?<![=!<>])=(?!=)', text):
        return False
    return all(m.group(1) in _READS or m.group(1) in _TYPE_WORDS for m in _CALL.finditer(text))


def _word(name):
    return re.compile(rf'(?<![\w.>]){re.escape(name)}(?!\w)')


def _squash(text):
    return re.sub(r'\s+', '', text)


def _wrap(expression):
    expression = expression.strip()
    call = re.match(rf'{IDENT}\s*\(', expression)
    if re.fullmatch(IDENT, expression) or (call and close(expression, call.end() - 1, '(', ')') == len(expression) - 1):
        return expression
    return f'({expression})'


def _find(source, part):
    clean = part.clean
    body_start, body_end = part.opening + 1, part.end
    for guard in _GUARD.finditer(clean, body_start, body_end):
        g, z = guard['g'], guard['z']
        if_close = close(clean, guard.end() - 1)
        if if_close < 0 or re.match(r'\s*else\b', clean[if_close + 1:]):
            continue
        head = clean[body_start:guard.start()]
        copy = re.search(rf'\b(?P<v>{IDENT})\s*=\s*{re.escape(g)}\s*;\s*$', head)
        load_head = head[:copy.start()] if copy else head
        load = re.search(rf'\b{re.escape(g)}\s*=\s*(?P<e>[^;{{}}]+);\s*$', load_head)
        if not load or not _pure(load['e']):
            continue
        v = copy['v'] if copy else g
        expr_start, expr_end = body_start + load.start('e'), body_start + load.end('e')
        expression = source[expr_start:expr_end].strip()
        position, prelude = guard.end(), []
        while True:
            assign = _ASSIGN.match(clean, position)
            if not assign or not _pure(assign['value']):
                break
            prelude.append(assign)
            position = assign.end()
        do = re.compile(r'\s*do\s*\{').match(clean, position)
        if not do:
            continue
        do_close = close(clean, do.end() - 1)
        if do_close < 0:
            continue
        tail = re.compile(rf'\s*while\s*\(\s*{re.escape(v)}\s*!=\s*{re.escape(z)}\s*\)\s*;\s*').match(clean, do_close + 1)
        if not tail or tail.end() != if_close:
            continue
        inner = clean[do.end():do_close]
        reload = re.search(rf'\b{re.escape(v)}\s*=\s*([^;{{}}]+);\s*$', inner)
        if not reload or _squash(reload.group(1)) != _squash(clean[expr_start:expr_end]):
            continue
        if re.search(r'\bgoto\b|\bcontinue\b|^\s*[A-Za-z_]\w*\s*:(?!:)', inner, re.M):
            continue
        body = inner[:reload.start()]
        uses = [m for m in _word(v).finditer(body)]
        if any(re.match(r'\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)', body[m.end():]) for m in uses):
            continue
        if uses:
            before = body[:uses[-1].start()]
            names = set(re.findall(IDENT, re.sub(r'M2C_FIELD\s*\([^()]*,\s*[^,()]*,', 'M2C_FIELD(', expression)))
            names |= set(re.findall(rf'M2C_FIELD\s*\(\s*({IDENT})', expression))
            if any(m.group(1) not in _READS and m.group(1) not in _TYPE_WORDS | {'if', 'while', 'for'}
                   for m in _CALL.finditer(before)):
                continue
            if any(re.search(rf'\b{re.escape(n)}\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)', before) for n in names):
                continue
        statement_start = body_start + load.start()
        whole = clean[part.opening:part.end]
        allowed = clean[statement_start:if_close + 1]
        stray = False
        for name in {g, v}:
            inside = len(_word(name).findall(allowed))
            declared = len(re.findall(rf'\b[A-Za-z_]\w*[\s*]+{re.escape(name)}\s*;', whole))
            stray = stray or len(_word(name).findall(whole)) != inside + declared
        if stray:
            continue
        yield {'start': statement_start, 'end': if_close + 1, 'v': v, 'z': z, 'expression': expression,
               'prelude': [(m['name'], source[m.start('value'):m.end('value')].strip(),
                            source[m.start():m.end()].strip()) for m in prelude],
               'body': source[do.end():do.end() + reload.start()], 'whole': whole}


def _render(found, inline):
    body = _word(found['v']).sub(lambda _: _wrap(found['expression']), found['body'])
    kept = []
    for name, value, statement in found['prelude']:
        assigned = len(re.findall(rf'\b{re.escape(name)}\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)', found['whole']))
        used_outside = len(_word(name).findall(found['whole'])) > (
            len(_word(name).findall(found['body'])) + len(_word(name).findall(statement))
            + len(re.findall(rf'\b[A-Za-z_]\w*[\s*]+{re.escape(name)}\s*;', found['whole'])))
        if inline and assigned == 1 and not used_outside:
            body = _word(name).sub(lambda _, v=value: _wrap(v), body)
        else:
            kept.append(statement)
    lines = ''.join(f'{s}\n' for s in kept)
    return f"{lines}while ({found['expression']} != {found['z']}) {{{body}}}"


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    children = []
    for found in list(_find(source, part))[:LIMIT]:
        for inline in (False, True):
            if inline and not found['prelude']:
                continue
            child = edit(source, [(found['start'], found['end'], _render(found, inline))])
            if child not in [c for _, c in children]:
                children.append((FAMILY, child))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
