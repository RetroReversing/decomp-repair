"""A test repeated to pick a value that is stored once, written as the one `if`/`else` store it came from.

A game that does something under a test and then asks the same test again to pick a value to store,

    if (c) { ...; }
    if (c) { *p = B; } else { *p = A; }

is jump threaded by gcc: the first test's false branch goes straight to the second test's false side, with `A` in its
delay slot. m2c reads that back with a temporary set before the first test and set again inside it:

    t = A;
    if (c) { ...; t = A; if (c) { t = B; } }
    *p = t;

The temporary is a variable of its own, so the value lands in another register than the one the game's two stores
share (an N64 object update, SN GCC 2.8.1 `-G0 -mips3 -O2`, 233 instructions: four register rows, `$a0` for `$v0`).
Dropping the temporary needs all of it at once: with the one-shot `do { } while (0)` fences a search had put around
the guarded block left in place it was still off (370), and the same `if`/`else` filling the temporary was too (515).

`repeated_select_store` writes the two stores after the guarded block, fences removed; `repeated_select_store_fenced`
keeps a fence the guarded block had. m2c also writes the shape with the store under a label in the outer `else` of a
`void` function's last statement,

    t = A;
    if (c) { ...; if (d) { ...; t = A; if (c) { t = B; } goto L; } } else { L: *p = t; REST }

where `repeated_select_store` writes `if (c) { ...; if (!d) { return; } ... }`, the two stores, then `REST`.

Meaning is kept: the second evaluation of `c` happens where the original either evaluated it too, or evaluated it with
nothing in between, `A` is set again inside the guard or is a constant, `c` has no call, assignment, step or `volatile`, and the temporary is named nowhere else. That the
threading is what gives the target's branch to the store with `A` in the delay slot is read from the target's
instructions; why the temporary takes another register is a hypothesis.
"""
import re

from .csource import _blank, find
from .goto_structure_repairs import blocks, parse, walk
from .pattern_repairs import close, negate

FAMILY = 'repeated_select_store'
FENCED_FAMILY = 'repeated_select_store_fenced'
FAMILIES = (FAMILY, FENCED_FAMILY)
IDENT = r'[A-Za-z_]\w*'
MAX_CHILDREN = 8
# a cast to a plain type, or an accessor macro: not a call, whatever parenthesis follows it
_CAST = re.compile(r'\(\s*(?:const\s+)?(?:unsigned\s+|signed\s+)?(?:[su](?:8|16|32|64)|f32|f64|char|short|int|long|float'
                   r'|void|M2C_UNK\w*|struct\s+\w+|[A-Z]\w*)\s*\**\s*\)')
_ACCESSOR = re.compile(r'\b(?:M2C_FIELD|FIELD|sizeof)\s*(?=\()')


def _squash(text):
    return re.sub(r'\s+', '', text)


def _pure(expr):
    plain = _ACCESSOR.sub('', _CAST.sub(' ', _blank(expr)))
    if re.search(r'\+\+|--|(?<![=!<>])=(?!=)|<<=|>>=|\bvolatile\b|\{', plain):
        return False
    return not re.search(r'[A-Za-z_\]]\w*\s*\(|[\])]\s*\(', plain)


def _mentions(text, name):
    return len(re.findall(r'(?<![\w.])(?<!->)' + name + r'\b', text))


class _Reader:
    def __init__(self, source, clean):
        self.source, self.clean = source, clean

    def text(self, start, end):
        return self.source[start:end]

    def assignment(self, stmt):
        """(left side, value) of a plain `left = value;` statement."""
        if stmt.kind != 'simple':
            return None
        hit = re.fullmatch(r'\s*([^;={}]+?)\s*(?<![-+*/%&|^<>!=])=(?!=)\s*([^;{}]+?)\s*;',
                           self.clean[stmt.start:stmt.end], re.S)
        if not hit:
            return None
        return (self.text(stmt.start + hit.start(1), stmt.start + hit.end(1)),
                self.text(stmt.start + hit.start(2), stmt.start + hit.end(2)))

    def condition(self, stmt):
        return self.text(*stmt.parts['cond']).strip()

    def unfenced(self, stmt):
        """The one statement of a `do { s } while (0);`, else the statement itself."""
        if stmt.kind == 'do' and _squash(self.condition(stmt)) == '0' and len(stmt.parts['body']['stmts']) == 1:
            return stmt.parts['body']['stmts'][0], True
        return stmt, False

    def select(self, stmts, var, condition):
        """The `[t = A;] if (c) { t = B; }` that ends `stmts`: (index of its first statement, A or None, B)."""
        if not stmts:
            return None
        last = stmts[-1]
        if last.kind != 'if' or _squash(self.condition(last)) != _squash(condition):
            return None
        then = last.parts['then']['stmts']
        chosen = self.assignment(then[0]) if len(then) == 1 else None
        if not chosen or chosen[0] != var:
            return None
        other = last.parts['other']
        if other is not None:
            spare = self.assignment(other['stmts'][0]) if len(other['stmts']) == 1 else None
            if not spare or spare[0] != var:
                return None
            return len(stmts) - 1, spare[1], chosen[1]
        before = self.assignment(stmts[-2]) if len(stmts) > 1 else None
        if before and before[0] == var:
            return len(stmts) - 2, before[1], chosen[1]
        return len(stmts) - 1, None, chosen[1]


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:])[0]


def _line_start(source, at):
    line = source.rfind('\n', 0, at) + 1
    return line if not source[line:at].strip() else at


def _line_end(source, at):
    hit = re.compile(r'[ \t]*\n').match(source, at)
    return hit.end() if hit else at


def _stores(indent, condition, target, chosen, spare):
    return (f'{indent}if ({condition}) {{\n{indent}    {target} = {chosen};\n{indent}}} else {{\n'
            f'{indent}    {target} = {spare};\n{indent}}}\n')


def _dedent(text, indent):
    """The lines of `text` moved so that the shallowest one starts at `indent`."""
    rows = text.strip('\n').split('\n')
    while rows and not rows[-1].strip():
        rows.pop()
    if not rows:
        return ''
    base = min(len(r) - len(r.lstrip()) for r in rows if r.strip())
    return ''.join((indent + r[base:].rstrip() if r.strip() else '') + '\n' for r in rows)


def _local(clean, opening, var):
    """The span of `var`'s own declaration line, when it declares nothing else."""
    hit = re.search(r'(?m)^[ \t]*(?:unsigned\s+|signed\s+)?[A-Za-z_]\w*[ \t]+\**' + var + r'[ \t]*;[ \t]*\n',
                    clean[opening:])
    if not hit or re.match(r'\s*return\b', hit[0]):
        return None
    return opening + hit.start(), opening + hit.end()


def _checked(reader, var, condition, target, values, uses, opening, end):
    """The temporary is a local named only in the statements replaced and its declaration; the rest is repeatable."""
    if not re.fullmatch(IDENT, var):
        return None
    declared = _local(reader.clean, opening, var)
    if not declared:
        return None
    whole = reader.clean[opening:end]
    if _mentions(whole, var) != uses + 1 or re.search(r'&\s*' + var + r'\b(?!\s*(?:\.|->|\[))', whole):
        return None
    if _mentions(_blank(condition), var) or _mentions(_blank(target), var):
        return None
    if not all(_pure(text) and not _mentions(_blank(text), var) for text in [condition, target, *values]):
        return None
    return declared


def _same_default(again, spare):
    """The value set again inside the guard is the first one; with none set again, the first must be a constant (it is
    now evaluated after the guarded statements)."""
    if again is None:
        return bool(re.fullmatch(r'\s*-?\s*(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?)[uUlLfF]*\s*', spare))
    return _squash(again) == _squash(spare)


def _escapes(stmts):
    """A jump or label that would change meaning when the statements around these move."""
    return any(s.kind in ('goto', 'label', 'case') or (s.kind == 'jump' and not loop) for s, loop in walk(stmts))


def _apply(source, edits):
    for start, end, new in sorted(edits, reverse=True):
        source = source[:start] + new + source[end:]
    return source


def _structured(reader, block, opening, end):
    """`t = A; [do {] if (c) {...; t = A; if (c) { t = B; }} [} while (0);] [do {] x = t; [} while (0);]`."""
    source = reader.source
    for first, guard, last in zip(block, block[1:], block[2:]):
        default = reader.assignment(first)
        if not default:
            continue
        var, spare = default
        test, fenced = reader.unfenced(guard)
        store, _ = reader.unfenced(last)
        stored = reader.assignment(store)
        if test.kind != 'if' or test.parts['other'] is not None or not stored or stored[1] != var:
            continue
        then = test.parts['then']
        if not then['block']:
            continue
        condition = reader.condition(test)
        stmts = then['stmts']
        select = reader.select(stmts, var, condition)
        if not select:
            continue
        at, again, chosen = select
        if not _same_default(again, spare):
            continue
        if _escapes(stmts):
            continue
        target = stored[0]
        selected = sum(_mentions(reader.clean[s.start:s.end], var) for s in stmts[at:])
        declared = _checked(reader, var, condition, target, [spare, chosen], 2 + selected, opening, end)
        if not declared:
            continue
        indent = _indent(source, guard.start)
        # inside the guarded block: everything before the select
        cut = (_line_start(source, stmts[at].start), _line_start(source, then['close'] - 1), '')
        inner = _apply(source[test.start:test.end], [(cut[0] - test.start, cut[1] - test.start, cut[2])])
        gone = (_line_start(source, first.start), _line_end(source, first.end), '')
        declaration = (declared[0], declared[1], '')
        tail = _stores(indent, condition, target, chosen, spare)
        shapes = [(FAMILY, indent + _dedent_block(inner, indent))]
        if fenced:
            shapes.append((FENCED_FAMILY, f'{indent}do {{\n{indent}    ' + _dedent_block(inner, indent + "    ").rstrip('\n')
                           + f'\n{indent}}} while (0);\n'))
        for family, head in shapes:
            body = (_line_start(source, guard.start), _line_end(source, last.end), head + tail)
            yield family, _apply(source, [declaration, gone, body])


def _dedent_block(block, indent):
    """An `if (...) { ... }` whose first line starts at its own offset, its later lines re-indented under `indent`."""
    head, _, rest = block.partition('\n')
    rows = rest.split('\n')
    closing = len(rows[-1]) - len(rows[-1].lstrip()) if rows else 0
    out = [head]
    for row in rows:
        if not row.strip():
            continue
        out.append(indent + row[min(closing, len(row) - len(row.lstrip())):].rstrip())
    return '\n'.join(out) + '\n'


def _labelled(reader, body, opening, end):
    """The same select, with the store under a label in the outer `else` of a `void` function's last statement."""
    source = reader.source
    if len(body) < 2:
        return
    first, outer = body[-2], body[-1]
    default = reader.assignment(first)
    if not default or outer.kind != 'if' or outer.parts['other'] is None:
        return
    var, spare = default
    then, other = outer.parts['then'], outer.parts['other']
    if not then['block'] or not other['block'] or not then['stmts'] or len(other['stmts']) < 2:
        return
    before, nested = then['stmts'][:-1], then['stmts'][-1]
    if _escapes(before):
        return
    if nested.kind != 'if' or nested.parts['other'] is not None or not nested.parts['then']['block']:
        return
    stmts = nested.parts['then']['stmts']
    label, store = other['stmts'][0], other['stmts'][1]
    if not stmts or stmts[-1].kind != 'goto' or label.kind != 'label':
        return
    name = label.parts['name']
    if stmts[-1].parts['target'] != name or len(re.findall(r'\bgoto\s+' + name + r'\b', reader.clean[opening:end])) != 1:
        return
    condition = reader.condition(outer)
    guard = reader.condition(nested)
    select = reader.select(stmts[:-1], var, condition)
    stored = reader.assignment(store)
    if not select or not stored or stored[1] != var:
        return
    at, again, chosen = select
    if not _same_default(again, spare) or _escapes(stmts[:-1]):
        return
    target = stored[0]
    selected = sum(_mentions(reader.clean[s.start:s.end], var) for s in stmts[at:-1])
    declared = _checked(reader, var, condition, target, [spare, chosen], 2 + selected, opening, end)
    if not declared:
        return
    indent = _indent(source, outer.start)
    skip = negate(guard) or f'!({guard})'
    prefix = _dedent(source[_line_start(source, before[0].start):_line_start(source, nested.start)], indent + '    ') \
        if before else ''
    kept = _dedent(source[_line_start(source, stmts[0].start):_line_start(source, stmts[at].start)], indent + '    ') \
        if at else ''
    rest = other['stmts'][2:]
    after = ''
    if rest:
        if any(s.kind == 'simple' and re.match(r'\s*(?:struct\s+)?[A-Za-z_]\w*\s+\**[A-Za-z_]\w*\s*[;=\[]',
                                               reader.clean[s.start:s.end]) for s in rest):
            return  # a declaration in the `else` block: it cannot move below statements
        after = _dedent(source[_line_start(source, rest[0].start):_line_start(source, other['close'] - 1)], indent)
    text = (f'{indent}if ({condition}) {{\n{prefix}{indent}    if ({skip}) {{\n{indent}        return;\n{indent}    }}\n'
            f'{kept}{indent}}}\n' + _stores(indent, condition, target, chosen, spare) + after)
    yield FAMILY, _apply(source, [(declared[0], declared[1], ''),
                                  (_line_start(source, first.start), _line_end(source, first.end), ''),
                                  (_line_start(source, outer.start), _line_end(source, outer.end), text)])


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    try:
        body = parse(clean, opening + 1, end - 1)
    except ValueError:
        return []
    reader = _Reader(source, clean)
    out = []
    for block in blocks(body):
        out.extend(_structured(reader, block, opening, end))
    if re.search(r'\bvoid\s+' + re.escape(name) + r'\s*\(', clean[:opening]):
        out.extend(_labelled(reader, body, opening, end))
    return out[:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
