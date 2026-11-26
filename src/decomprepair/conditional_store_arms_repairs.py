"""A value picked into a temporary only to be stored once, written as the stores it came from.

When two or more arms each end in a store to one place, gcc cross-jumps the stores into one and m2c reads that back
as a temporary: `t = A; if (c) { t = B; } *p = t;`, often with one arm's store reached by a `goto` into the other
arm's tail. The temporary is a second value in a register of its own (an N64 text converter, gcc 2.7.2 KMC: four
register rows), where the game's `if (c) { *p = B; } else { *p = A; }` leaves the value in the register the tail
merge picks. Neither half of that is enough alone, so one child does all of it:

1. `if (c) { ...; goto L; } if (d) { ... t = X; L: *p = t; q++; }` gets the labelled run in the first arm and the
   second `if` as its `else`;
2. every `t = A; if (c) { t = B; } store = t;` becomes two stores, and every `t = A; store = t;` one,
   where `t` is not read again.

`conditional_store_arms` does both, `conditional_store_arms_keep_goto` only the second.
"""
import re

from . import local_flow
from .csource import _blank, find
from .goto_structure_repairs import _gotos, blocks, parse
from .pattern_repairs import close

FAMILY = 'conditional_store_arms'
KEEP_FAMILY = 'conditional_store_arms_keep_goto'
FAMILIES = (FAMILY, KEEP_FAMILY)

IDENT = r'[A-Za-z_]\w*'
NARROW = {'u8': 'u8', 's8': 's8', 'char': 's8', 'u16': 'u16', 's16': 's16', 'short': 's16',
          'unsigned char': 'u8', 'signed char': 's8', 'unsigned short': 'u16'}
MAX_SITES = 16
# a cast to a plain type: not a call, whatever parenthesis follows it
_CAST = re.compile(r'\(\s*(?:unsigned\s+|signed\s+)?(?:[su](?:8|16|32)|f32|char|short|int|long|float|void)\s*\**\s*\)')


def _function(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    try:
        return clean, parse(clean, opening + 1, end - 1)
    except ValueError:
        return None


def _inline_goto_once(source, name):
    """One `goto` into the tail of the next `if`, given its own copy of the tail; the next `if` becomes its `else`."""
    parsed = _function(source, name)
    if not parsed:
        return None
    clean, body = parsed
    for block in blocks(body):
        for first, second in zip(block, block[1:]):
            if first.kind != 'if' or second.kind != 'if' or first.parts['other'] is not None:
                continue
            then = first.parts['then']
            if not then['block'] or not then['stmts'] or then['stmts'][-1].kind != 'goto':
                continue
            jump = then['stmts'][-1]
            label = jump.parts['target']
            if len(_gotos(body, label)) != 1:
                continue
            for arm in (second.parts['then'], second.parts['other']):
                if not arm or not arm['block']:
                    continue
                stmts = arm['stmts']
                at = next((k for k, s in enumerate(stmts) if s.kind == 'label' and s.parts['name'] == label), None)
                if at is None:
                    continue
                run = stmts[at + 1:]
                if not run or any(s.kind != 'simple' for s in run):
                    continue
                tail = ' '.join(source[s.start:s.end] for s in run)
                # the label comes after the goto: removing it first leaves the earlier offsets as they were
                text = source[:stmts[at].start] + source[stmts[at].end:]
                return (text[:jump.start] + tail + text[jump.end:then['close']] + ' else '
                        + text[then['close']:].lstrip())
    return None


def _assignment(clean, source, stmt, var=None):
    """(variable, value) of a plain `variable = value;` statement."""
    if stmt.kind != 'simple':
        return None
    hit = re.fullmatch(r'\s*(' + IDENT + r')\s*=(?!=)\s*([^;]+);', clean[stmt.start:stmt.end], re.S)
    if not hit or (var and hit[1] != var):
        return None
    return hit[1], source[stmt.start + hit.start(2):stmt.start + hit.end(2)].strip()


def _pure(expr):
    """No call, assignment or step: the expression may be evaluated on one path only."""
    plain = _CAST.sub(' ', _blank(expr))
    if re.search(r'\+\+|--|(?<![=!<>])=(?!=)|<<=|>>=', plain):
        return False
    return not re.search(r'[\w\])]\s*\(', plain)


def _uses(expr, var):
    return re.search(r'(?<![\w.>])' + var + r'\b', _blank(expr)) is not None


def _dead_after(flow, variable, pos):
    node = flow.at(pos)
    return node is not None and all(variable not in flow.nodes[n].live for n in node.successors)


def _sites(source, name, flow):
    """[(start, end, replacement)] for each temporary that only feeds one store."""
    parsed = _function(source, name)
    if not parsed or flow is None:
        return []
    clean, body = parsed
    found = []
    for block in blocks(body):
        for k, store in enumerate(block):
            if store.kind != 'simple' or not k:
                continue
            hit = re.fullmatch(r'\s*([^;={}]+?)\s*=(?!=)\s*(' + IDENT + r')\s*;', clean[store.start:store.end], re.S)
            if not hit:
                continue
            var = hit[2]
            lhs = source[store.start + hit.start(1):store.start + hit.end(1)].strip()
            declared = next((d for d in flow.locals if d['name'] == var), None)
            if declared is None or lhs == var or _uses(lhs, var) or not _pure(lhs):
                continue
            if not lhs.startswith(('*', '(*')) and not re.search(r'[\[.]|->', lhs) and any(
                    d['name'] == lhs for d in flow.locals):
                continue  # a copy between locals is not a store
            condition, other = None, None
            previous = block[k - 1]
            first = k - 1
            if previous.kind == 'if' and previous.parts['other'] is None and k >= 2:
                inner = previous.parts['then']['stmts']
                chosen = _assignment(clean, source, inner[0], var) if len(inner) == 1 else None
                if not chosen:
                    continue
                condition = source[slice(*previous.parts['cond'])].strip()
                other = chosen[1]
                first = k - 2
            default = _assignment(clean, source, block[first], var)
            if not default:
                continue
            value = default[1]
            if _uses(value, var) or not _pure(value):
                continue
            if condition is not None and (_uses(condition, var) or _uses(other, var) or not _pure(condition)
                                          or not _pure(other)):
                continue
            if not _dead_after(flow, var, store.start):
                continue
            narrow = NARROW.get(' '.join(declared['type'].split()))
            if narrow and not _byte_store(source, lhs, narrow):
                value = f'({narrow}) ({value})'
                other = f'({narrow}) ({other})' if other is not None else None
            if condition is None:
                text = f'{lhs} = {value};'
            else:
                text = f'if ({condition}) {{ {lhs} = {other}; }} else {{ {lhs} = {value}; }}'
            found.append((block[first].start, store.end, text))
            if len(found) >= MAX_SITES:
                return found
    return found


def _byte_store(source, lhs, narrow):
    """`*p = t;` where `p` is declared a pointer no wider than the temporary: the store narrows by itself."""
    hit = re.fullmatch(r'\*\s*(' + IDENT + r')', lhs)
    if not hit:
        return False
    widths = {'u8': 1, 's8': 1, 'char': 1, 'u16': 2, 's16': 2, 'short': 2}
    declared = re.search(r'\b(u8|s8|u16|s16|char|short)\s*\*\s*' + hit[1] + r'\b', _blank(source))
    return bool(declared) and widths[declared[1]] <= widths[narrow]


def _rewrite(source, name):
    flow = local_flow.analyze(source, name)
    sites = _sites(source, name, flow)
    if not sites:
        return None
    text = source
    taken = len(source) + 1
    for start, end, new in sorted(sites, reverse=True):
        if end > taken:
            continue
        text = text[:start] + new + text[end:]
        taken = start
    return text


def variants(source, name):
    result = []
    inlined = source
    for _ in range(4):
        step = _inline_goto_once(inlined, name)
        if step is None:
            break
        inlined = step
    if inlined != source:
        text = _rewrite(inlined, name)
        if text:
            result.append((FAMILY, text))
    text = _rewrite(source, name)
    if text:
        result.append((KEEP_FAMILY if inlined != source else FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
