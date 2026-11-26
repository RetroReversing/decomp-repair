"""A compare inside an `if` arm held in a flag local, the same local staging a store's value in the `else` arm.

The shape (SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mfp32`; a 145-instruction N64 positional-sound update, 210 -> 205 in the
app's judge, 110 -> 105 under `-mfp32`): the then-arm clamps a stored volume against a table entry,
`o->vol = q; if (D[ch] < o->vol) o->vol = D[ch];`, and the else arm stores a product, `o->x64 = o->x70 * 100;`.
Written as

    t = D[ch] < o->vol;          /* then arm */
    if (t) { ... }
    ...
    t = o->x70 * 100;            /* else arm */
    o->x64 = t;

the compare's result (`slt`) is one local the two arms share. A local named in two basic blocks is a global-allocator
pseudo rather than a block-local quantity, so its register is chosen after the arms' block-local values (here `slt
$v0` where the plain compare took `$a0`). Neither edit moves anything alone (the flag alone, or the staging alone: 210);
the pair is offered as one child. Which allocator places the flag is a hypothesis read from local-alloc.c and global.c;
the score is the evidence.

Offered for an `if (...) { A } else [if (...)] { B }` where A holds an `if` whose whole condition is one relational
compare (`<`, `>`, `<=`, `>=`) of two operands with no assignment, call, `&&`, `||` or `?:`, and B holds a statement
`LHS = E;` whose value E is an integer expression with an operator and no call. The flag is a fresh `int` local
declared at the top of the function. A candidate; the judge decides.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'compare_flag_arm_share'
FAMILIES = (FAMILY,)
LIMIT = 8
IF = re.compile(r'\bif\s*\(')
RELATIONAL = re.compile(r'^(?P<a>[^<>=!]+?)\s*(?P<op><=|>=|<(?![<=])|>(?![>=]))\s*(?P<b>[^<>=!]+)$')
STORE = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>[^;{}=\n]+?)\s*=(?!=)\s*(?P<value>[^;{}\n]+);')
FLOATISH = re.compile(r'\d\.\d|\d[fF]\b|\b(?:f32|f64|float|double)\b')


def _after_space(clean, pos):
    while pos < len(clean) and clean[pos].isspace():
        pos += 1
    return pos


def _block(clean, pos):
    """(open, close) of the `{ ... }` block starting at `pos` (after spaces), else None."""
    pos = _after_space(clean, pos)
    if pos >= len(clean) or clean[pos] != '{':
        return None
    end = close(clean, pos, '{', '}')
    return (pos, end) if end else None


def _else_block(clean, pos):
    """The block of the `else` (or `else if (...)`) that follows position `pos`, else None."""
    pos = _after_space(clean, pos)
    if not clean.startswith('else', pos) or (pos + 4 < len(clean) and (clean[pos+4].isalnum() or clean[pos+4] == '_')):
        return None
    pos = _after_space(clean, pos + 4)
    if clean.startswith('if', pos):
        found = IF.match(clean, pos)
        if not found:
            return None
        stop = close(clean, found.end() - 1)
        return _block(clean, stop) if stop else None
    return _block(clean, pos)


def _simple_compare(condition):
    inner = condition.strip()
    if re.search(r'&&|\|\||\?|[^=!<>]=[^=]|\w\s*\(', inner):
        return None
    found = RELATIONAL.match(inner)
    if not found or FLOATISH.search(inner):
        return None
    return found


def _fresh(clean):
    for name in ('flag', 'cmp', 'test', 'less'):
        if not re.search(rf'\b{name}\b', clean):
            return name
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    flag = _fresh(clean)
    if not flag:
        return []
    top = part.opening + 1
    line_end = source.find('\n', top)
    indent = re.match(r'\s*', source[line_end+1:])[0].replace('\n', '') if line_end >= 0 else '    '
    declaration = f'\n{indent or "    "}int {flag};'
    result = []
    for outer in IF.finditer(clean, part.opening, part.end):
        stop = close(clean, outer.end() - 1)
        then = _block(clean, stop) if stop else None
        other = _else_block(clean, then[1]) if then else None
        if not other:
            continue
        compares = []
        for inner in IF.finditer(clean, then[0], then[1]):
            paren = inner.end() - 1
            end = close(clean, paren)
            if end and _simple_compare(clean[paren+1:end-1]):
                compares.append((inner.start(), paren, end))
        stores = []
        for found in STORE.finditer(clean, other[0] + 1, other[1] - 1):
            value = found['value'].strip()
            operators = value.replace('->', '.')
            if (re.search(r'[-+*/%&|^]|<<|>>', operators) and not re.fullmatch(r'-?\s*\w+', value)
                    and not re.search(r'\w\s*\(|[?]', value)
                    and not FLOATISH.search(value) and found['lhs'].strip() != flag):
                stores.append(found)
        for start, paren, end in compares:
            line = source.rfind('\n', 0, start) + 1
            pad = source[line:start] if not source[line:start].strip() else '    '
            for store in stores:
                lhs, value = store['lhs'].strip(), store['value'].strip()
                edits = [(top, top, declaration),
                         (start, end, f'{flag} = {source[paren+1:end-1].strip()};\n{pad}if ({flag})'),
                         (store.start('lhs'), store.end(),
                          f'{flag} = {source[store.start("value"):store.end("value")].strip()};\n'
                          f'{store["indent"]}{source[store.start("lhs"):store.end("lhs")].strip()} = {flag};')]
                if lhs and value:
                    result.append((FAMILY, edit(source, edits)))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
