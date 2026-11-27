"""A store m2c made once after an if/else, from a variable each arm set last, written in each arm instead.

When both arms of an `if` end by storing to the same place, gcc keeps the two stores, or merges them into one after the
join, depending on what each arm computed. m2c reads the merged form back as a variable each arm sets, stored once:

    if (c) {
        f();
        v = (M2C_FIELD(p, s32 *, 0x28) & ~0xFC) | 0x14;
    } else {
        g();
        v = (M2C_FIELD(p, s32 *, 0x28) & ~0xFC) | 0x1C;
    }
    M2C_FIELD(p, s32 *, 0x28) = v;

An N64 function was 99.3% this way: the shared value lived in a saved register, so the addresses loaded before a later
call came in the other order. With the store written at the end of each arm and the variable gone, it was exact.
Offered only when the variable is set nowhere but the two arms' last statements and read nowhere but the stores.

m2c also reads back a run of stores of one value after the join, such as the three colour bytes of an object:

    } else {
        v = 0x2D - (timer * 2);
    }
    p->r = v;
    p->g = v;
    p->b = v;

An N64 object update (SN GCC 2.8.1, `-O2`) had the stores in both arms (100 -> 0): with the value joined, the variable
lives across the join and takes `$v1`; stored in each arm it stays in `$v0` and gcc merges the stores again. The whole
run goes to the end of each arm. An arm whose value is a literal that the variable's type holds stores the literal; any
other arm keeps `v = E;` and stores `v`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'carried_store_arms'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def _last_assignment(arm, var):
    """The span (in `arm`) of a trailing `var = E;` statement, and E's span, or None."""
    hit = re.search(r'(?m)^([ \t]*)' + var + r'\s*=(?!=)\s*([^;]+);\s*$', arm)
    if not hit:
        return None
    return hit


_RANGES = {'u8': (0, 0xFF), 's8': (-0x80, 0x7F), 'u16': (0, 0xFFFF), 's16': (-0x8000, 0x7FFF),
           'u32': (0, 0xFFFFFFFF), 's32': (-0x80000000, 0x7FFFFFFF), 'int': (-0x80000000, 0x7FFFFFFF),
           'unsigned char': (0, 0xFF), 'signed char': (-0x80, 0x7F), 'unsigned short': (0, 0xFFFF),
           'short': (-0x8000, 0x7FFF)}


def _literal_held(text, kind):
    """True when `text` is an integer literal that a variable of type `kind` holds unchanged."""
    hit = re.fullmatch(r'(-?)(0[xX][0-9a-fA-F]+|[1-9]\d*|0)', text)
    if not hit or kind not in _RANGES:
        return False
    value = int(hit[2], 0) * (-1 if hit[1] else 1)
    low, high = _RANGES[kind]
    return low <= value <= high


def _run_after(body, store, var):
    """The stores of `var` that follow `store` one line after another, as matches in `body`."""
    run = [store]
    follow = re.compile(r'(?P<indent>[ \t]*)(?P<lhs>[^;={}\n]+?)\s*=(?!=)\s*' + var + r'\s*;[ \t]*\n')
    while True:
        hit = follow.match(body, run[-1].end())
        if not hit or re.search(r'\b' + var + r'\b', hit['lhs']):
            return run
        run.append(hit)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    result = []
    for store in re.finditer(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>[^;={}\n]+?)\s*=(?!=)\s*(?P<var>' + IDENT + r')\s*;[ \t]*\n',
                             clean[opening:end]):
        var, lhs = store['var'], store['lhs'].strip()
        if var == lhs or re.search(r'\b' + var + r'\b', lhs):
            continue
        at = opening + store.start()
        # the statement right before it is an if/else: walk back over the else arm
        before = clean[:at].rstrip()
        if not before.endswith('}'):
            continue
        else_close = len(before)
        else_open = _opening_brace(clean, else_close - 1)
        if else_open is None or not re.search(r'\belse\s*$', clean[:else_open]):
            continue
        else_kw = re.search(r'\belse\s*$', clean[:else_open]).start()
        if_close = len(clean[:else_kw].rstrip())
        if clean[if_close - 1:if_close] != '}':
            continue
        if_open = _opening_brace(clean, if_close - 1)
        if if_open is None:
            continue
        arms = [(if_open + 1, if_close - 1), (else_open + 1, else_close - 1)]
        lasts = []
        for a, b in arms:
            arm = clean[a:b]
            last = _last_assignment(arm, var)
            if not last or arm[last.end():].strip():
                lasts = None
                break
            # (only up to the statement's `;`: what follows, the arm's closing line, stays as it was)
            semicolon = arm.find(';', last.end(2)) + 1
            lasts.append((a + last.start(), a + semicolon, a + last.start(2), a + last.end(2), last.group(1)))
        if not lasts:
            continue
        # the variable appears nowhere else in the function (its declaration aside)
        run = _run_after(clean[opening:end], store, var)
        mentions = [m.start() + opening for m in re.finditer(r'(?<![\w.>])' + var + r'\b', body)]
        declared = re.search(r'(?m)^[ \t]*(?P<kind>[\w ]+?)\s+\**' + var + r'\s*;[ \t]*\n', clean[opening:if_open])
        inside = [p for p in mentions if any(s <= p < e for s, e, _, _, _ in lasts)]
        others = [p for p in mentions if p not in inside and not (at <= p < opening + run[-1].end())
                  and not (declared and opening + declared.start() <= p < opening + declared.end())]
        if len(inside) != 2 or others:
            continue
        text = source
        targets = [source[opening + hit.start('lhs'):opening + hit.end('lhs')].strip() for hit in run]
        edits = [(opening + store.start(), opening + run[-1].end(), '')]
        kept = False
        for s, e, vs, ve, indent in lasts:
            value = source[vs:ve].strip()
            if len(targets) == 1:
                lines = [f'{targets[0]} = {value};']
            elif declared and _literal_held(value, ' '.join(declared['kind'].split())):
                lines = [f'{target} = {value};' for target in targets]
            else:
                kept = True
                lines = [f'{var} = {value};'] + [f'{target} = {var};' for target in targets]
            edits.append((s, e, '\n'.join(indent + line for line in lines)))
        if declared and not kept:
            edits.append((opening + declared.start(), opening + declared.end(), ''))
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
        result.append((FAMILY, text))
        if len(result) >= 3:
            break
    return result


def _python_opening_brace(text, closing):
    depth = 0
    for pos in range(closing, -1, -1):
        depth += (text[pos] == '}') - (text[pos] == '{')
        if depth == 0:
            return pos
    return None


_opening_brace = _python_opening_brace
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _opening_brace(text, closing):
        found = _scan.open_every(text, closing, '{', '}', None)
        return _python_opening_brace(text, closing) if found is NotImplemented else found
