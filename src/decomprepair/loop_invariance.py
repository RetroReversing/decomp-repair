"""Whether an expression set before a loop still has the same value on every pass, so a rewrite may repeat it there.

A repair must not change what the program does. `stepped_induction_index` and `integer_cursor_for_loop` move a cursor's
start (or a loop's bound) to each use inside the loop, and ask here first: only literals, addresses, and locals or
parameters that neither the loop nor a pointer can write, set where they run again before each entry of the loop. A
global, a dereference or a call is not proven, and is refused.
"""
import re

from .integer_repair_support import IDENT
from .pattern_repairs import close

WORD = re.compile(rf'(?<![\w.])(?<!->)\b(?P<v>{IDENT})\b(?P<after>\s*[(\[.]|\s*->)?')
# only what is surely a cast: `(mask) & x` and `(count) - 1` read the name in the parentheses
CAST = re.compile(rf'\(\s*(?:const\s+)?(?:(?:(?:unsigned|signed)(?:\s+(?:char|short|int|long))*|struct\s+{IDENT}'
                   r'|[su](?:8|16|32|64)|u?int(?:8|16|32|64|ptr)_t|size_t|char|short|int|long|float|double|f32|f64|void)'
                   rf'[\s*]*|{IDENT}\s*\*[\s*]*)\)')
_SIDE_EFFECT = re.compile(r'\+\+|--|<<=|>>=|(?<![=!<>])=(?!=)')


def declared(part, name):
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


def written(text, name):
    return re.search(rf'\b{name}\b\s*(?:=(?!=)|\+\+|--|(?:[-+*/|&^%]|<<|>>)=)|(?:\+\+|--)\s*{name}\b|(?<!&)&\s*{name}\b', text)


def _escaped(part, name):
    """Whether the function takes the local's address anywhere, so a store or a callee in the loop may write it."""
    body = CAST.sub(' ', part.body)
    for hit in re.finditer(rf'(?<!&)&[\s(]*{name}\b', body):
        before = body[:hit.start()].rstrip()
        # after a name or `]` the `&` is binary; after `)` it may follow a typedef's cast, so it counts
        if re.search(r'\breturn$', before) or not re.search(r'[\w\]]$', before):
            return True
    return False


def stable(part, expression, between):
    """Whether `expression` reads only locals, parameters, addresses and literals that nothing in `between` can write."""
    plain = CAST.sub(' ', expression).strip()
    if _SIDE_EFFECT.search(plain):
        return False
    for star in re.finditer(r'\*', plain):
        if not re.search(r'[\w)]$', plain[:star.start()].rstrip()):
            return False  # a dereference: memory a call or a store in the loop may change
    for word in WORD.finditer(plain):
        if word['after']:
            return False
        before = plain[:word.start()].rstrip()
        if before.endswith('&') and not before.endswith('&&') and not re.search(r'[\w\])]$', before[:-1].rstrip()):
            continue  # `&name`: an address, the same whatever the name holds
        if not declared(part, word['v']) or written(between, word['v']) or _escaped(part, word['v']):
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


def runs_each_time(before, start):
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
