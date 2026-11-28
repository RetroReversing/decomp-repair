"""m2c's hand-reduced copy loop (guard, integer cursors, a bound local) written back as the indexed `for` loop.

m2c shows the loop pass's own work as source: a guard on the trip count, one integer variable per induction variable
the compiler made, each started in the guard and stepped beside the counter, and the bound the compiler hoisted held in
a local with a copy of itself:

    n = size >> 2;
    i = 0;
    if (n != 0) {
        n = n;
        dst = base & MASK;
        src = base;
        do {
            put((s32 *) dst, get(src));
            dst += 4;
            i += 1;
            src += 4;
        } while (i < n);
    }

The game wrote `for (i = 0; i < (size >> 2); i++) put((s32 *) ((base & MASK) + i * 4), get(base + i * 4));`. The
compiler then hoists the shift and the mask, makes the two stepped registers and copies the entry test's value into the
bound's register itself. Measured on one 63-instruction N64 copy routine (SN GCC 2.8.1, `-G0 -mips3 -O2`): the saved
best at 160; the three edits together 0. Apart they do not help: cursors alone 160, with the `for` loop 110, and the
`for` loop that keeps its stepped cursors 1096. So they are one child. Why the loop pass orders the registers this way
is not read from the compiler's source (hypothesis).

`integer_cursor_for_loop` writes the cursors as the counter's multiples (`stepped_induction_index`), the guarded loop
as a `for` (`counted_loop_shapes`) and the bound's expression in the test; `integer_cursor_for_loop_bound_local` keeps
the bound local, for a target that holds the bound in a register of the source's own. Offered only when every start the
rewrite repeats, whatever its step (one included), reads only literals, addresses, and locals or parameters that neither
the loop nor a pointer can write, and the start runs again before each entry of the loop, so it is the same value on every
pass. A global, a dereference or a call is refused. The exact judge decides.
"""
import re

from . import counted_loop_shapes, stepped_induction_index
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'integer_cursor_for_loop'
BOUND_LOCAL = 'integer_cursor_for_loop_bound_local'
FAMILIES = (FAMILY, BOUND_LOCAL)
_FOR = re.compile(rf'\bfor\s*\(\s*(?P<i>{IDENT}) = 0; (?P=i) < (?P<n>{IDENT});')
_WORD = re.compile(rf'(?<![\w.])(?<!->)\b(?P<v>{IDENT})\b(?P<after>\s*[(\[.]|\s*->)?')
# only what is surely a cast: `(mask) & x` and `(count) - 1` read the name in the parentheses
_CAST = re.compile(rf'\(\s*(?:const\s+)?(?:(?:(?:unsigned|signed)(?:\s+(?:char|short|int|long))*|struct\s+{IDENT}'
                   r'|[su](?:8|16|32|64)|u?int(?:8|16|32|64|ptr)_t|size_t|char|short|int|long|float|double|f32|f64|void)'
                   rf'[\s*]*|{IDENT}\s*\*[\s*]*)\)')
_SIDE_EFFECT = re.compile(r'\+\+|--|<<=|>>=|(?<![=!<>])=(?!=)')


def _declared(part, name):
    """The type a local or parameter of the function is declared with, or None."""
    head = part.clean[:part.opening]
    params = head[head.rfind('(') + 1:head.rfind(')')]
    body = part.clean[part.opening:part.end]
    tail = rf'\s*(?!(?:return|else|case|goto|do)\b)(?P<type>[A-Za-z_][\w ]*?[\s*]+)\b{name}\b\s*(?=[;,=)]|$)'
    # in the body a comma separates call arguments (`f(a, b * name)`), so only a statement can declare
    hit = re.search(r'(?:^|[;{}])' + tail, body, re.M) or re.search(r'(?:^|,)' + tail, params, re.M)
    words = hit['type'].split() if hit else []
    # `extern` names a global and a `static` outlives the call: a callee can reach either
    return ' '.join(words) if words and not {'extern', 'static'} & set(words) else None


def _written(text, name):
    return re.search(rf'\b{name}\b\s*(?:=(?!=)|\+\+|--|(?:[-+*/|&^%]|<<|>>)=)|(?:\+\+|--)\s*{name}\b|(?<!&)&\s*{name}\b', text)


def _escaped(part, name):
    """Whether the function takes the local's address anywhere, so a store or a callee in the loop may write it."""
    body = _CAST.sub(' ', part.body)
    for hit in re.finditer(rf'(?<!&)&[\s(]*{name}\b', body):
        before = body[:hit.start()].rstrip()
        # after a name or `]` the `&` is binary; after `)` it may follow a typedef's cast, so it counts
        if re.search(r'\breturn$', before) or not re.search(r'[\w\]]$', before):
            return True
    return False


def _stable(part, expression, between):
    """Whether `expression` reads only locals, parameters, addresses and literals that nothing in `between` can write."""
    plain = _CAST.sub(' ', expression).strip()
    if _SIDE_EFFECT.search(plain):
        return False
    for star in re.finditer(r'\*', plain):
        if not re.search(r'[\w)]$', plain[:star.start()].rstrip()):
            return False  # a dereference: memory a call or a store in the loop may change
    for word in _WORD.finditer(plain):
        if word['after']:
            return False
        before = plain[:word.start()].rstrip()
        if before.endswith('&') and not before.endswith('&&') and not re.search(r'[\w\])]$', before[:-1].rstrip()):
            continue  # `&name`: an address, the same whatever the name holds
        if not _declared(part, word['v']) or _written(between, word['v']) or _escaped(part, word['v']):
            return False
    return True


def _once_block(before_brace):
    """Whether the brace after `before_brace` opens a block run at most once for each time it is reached."""
    head = before_brace.rstrip()
    if re.search(r'\belse$', head):
        return True
    # `if (..) {`, but not the `if` that is a braceless loop's whole body
    return any(close(head, hit.end() - 1, '(', ')') == len(head)
               for hit in re.finditer(r'(?:^|[;{}]|\belse)\s*if\s*\(', head))


def _runs_each_time(before, start):
    """Whether a start surely runs before each entry of the loop that follows `before`.

    The start is its own statement (no braceless `if` or loop), its block is not left before the loop, and the blocks
    opened on the way that still hold the loop are `if`s, not loops that would enter it again without the start.
    """
    lead = before[:start.start()].rstrip()
    if lead and lead[-1] not in ';{}' or re.search(r'\bgoto\b', before):
        return False
    between = before[start.end():]
    opened = []
    for brace in re.finditer(r'[{}]', between):
        if brace[0] == '{':
            opened.append(brace.start())
        elif opened:
            opened.pop()
        else:
            return False
    # the last `do` of `before` is the rewritten loop's own, whose brace comes after `before`
    return all(_once_block(between[:at]) for at in opened)


def _starts_stable(part):
    """Whether every start `stepped_induction_index`'s first child would repeat is the same value on every pass."""
    clean = part.clean
    for loop in stepped_induction_index._loops(part):
        opening, end, tail, run, strides = loop
        before = clean[part.opening + 1:opening]
        # `before` ends with the loop's `do`; its brace is `opening`
        assigns = list(stepped_induction_index._ASSIGN.finditer(before))
        for counter in [v for v, k in strides.items() if k == 1]:
            zero = [a for a in assigns if a['v'] == counter]
            if not zero or zero[-1]['init'].strip() not in ('0', '0U'):
                continue
            # the same choice, in the same order, as the child `variants` takes
            chosen = [v for v in strides if v != counter
                      and stepped_induction_index._plan(part, loop, counter, v, strides[v])]
            if not chosen:
                continue
            unstepped = clean[opening + 1:end - 1][:run[0].start()] + tail['cond']
            if not _runs_each_time(before, zero[-1]) or _written(before[zero[-1].end():] + unstepped, counter):
                return False
            for var in chosen:
                start = [a for a in assigns if a['v'] == var][-1]
                between = before[start.end():] + clean[opening:end + tail.end()]
                if not _runs_each_time(before, start) or not _stable(part, start['init'].strip(), between):
                    return False
            return True
    return False


def _inline_bound(source, name):
    """`n = EXPR; ... for (i = 0; i < n; ..)` with EXPR written in the test, when the test is the only reader of n."""
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    for loop in _FOR.finditer(clean, part.opening, part.end):
        n = loop['n']
        kind = _declared(part, n)
        body = clean[part.opening + 1:part.end - 1]
        offset = part.opening + 1
        copies = list(re.finditer(rf'(?m)^[ \t]*{n} = {n};[ \t]*\n', body))
        sets = [s for s in re.finditer(rf'(?m)^[ \t]*{n} = (?P<value>[^;{{}}=]+);[ \t]*\n', body)
                if s['value'].strip() != n]
        if not kind or len(sets) != 1 or offset + sets[0].end() > loop.start():
            continue
        if not _runs_each_time(body[:loop.start() - offset], sets[0]):
            continue
        declaration = re.search(rf'(?m)^[ \t]*{re.escape(kind)}\s*\b{n}\s*;', body)
        known = [(s.start(), s.end()) for s in copies + sets] + ([declaration.span()] if declaration else [])
        known.append((loop.start('n') - offset, loop.end('n') - offset))
        if any(not any(a <= use.start() < b for a, b in known) for use in re.finditer(rf'\b{n}\b', body)):
            continue
        value = sets[0]['value'].strip()
        opening = clean.find('(', loop.start())
        header_end = close(clean, opening, '(', ')')
        brace = clean.find('{', header_end) if header_end else -1
        loop_end = close(clean, brace, '{', '}') if brace >= 0 else None
        if not loop_end or not _stable(part, value, clean[offset + sets[0].end():loop_end]):
            continue
        words = [w['v'] for w in _WORD.finditer(_CAST.sub(' ', value))]
        text = f'({value})' if all(_declared(part, w) == kind for w in words) else f'({kind})({value})'
        edits = [(offset + s.start(), offset + s.end(), '') for s in copies + sets]
        edits.append((loop.start('n'), loop.end('n'), text))
        return edit(source, edits)
    return None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.clean[part.opening:part.end]) or not _starts_stable(part):
        return []
    indexed = stepped_induction_index.variants(source, name)
    if not indexed:
        return []
    text = indexed[0][1]
    for family, child in counted_loop_shapes.variants(text, name):
        if family != 'counted_for_loop':
            continue
        child = re.sub(r'(?m)\n[ \t]*\n(?=for \()', '\n', child)
        inlined = _inline_bound(child, name)
        return ([(FAMILY, inlined)] if inlined else []) + [(BOUND_LOCAL, child)]
    return []


REPAIR = {
    'families': FAMILIES,
    'variants': variants,
    'needs': ('source', 'name'),
    'order': 400,
}
