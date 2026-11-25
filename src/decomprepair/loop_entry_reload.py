"""A do-while whose test variable is read before the loop and again at its end, written as the while it stands for.

m2c turns `while (*p != 0) { ... }` that sits under an `if (base[0] != 0)` into

    v = *p; n = 0;                      (often under an `if (g) { same } else { same }` guard)
    do { ...; p += ...; v = *p; n = 0; } while (v != 0);

On KMC GCC 2.7.2 (N64) the entry read is folded into the `if`'s own load of the same byte (cse sees both), while the
target keeps a second `lb` of the byte right before the loop: the loop's duplicated entry test, whose branch jump
optimization removes (the enclosing `if` proved it taken) but whose load stays. Written as `n = 0; while (*p != 0)
{ v = *p; ...; n = 0; }` the compiler duplicates the test itself and the extra load appears. A text-layout function
went 390 -> 365 on this edit (the second of five steps to 95): one load row, and its register rows followed. Hypothesis
(not confirmed in the compiler's source): jump.c's loop-test duplication keeps the load when it was written inside
the loop test; the measured fact is the 390 -> 365.

Children, for a `do { ... v = E; X...; } while (v != 0);` whose body has no `continue` of its own and which sits right
after the same `v = E; X...;` (possibly inside an `if (c) { S } else { S }` of identical arms, which is dropped), and
whose first test is proved taken: the loop sits in an `if (G != 0)` / `if (G)` block and `p = G;` was written before it
(E being `*p`), or `v` itself was tested by an `if` that encloses the loop. The statements `X` (assignments of constants)
stay at the end of the body and are also written once before the `while`; and, when nothing after the loop reads them,
a second child with them only at the top of the body (reorg then fills the loop-back branch's delay slot with the first
of them and the preamble's order of the load and the constant follows the target's: 95 -> 35 on the same function).
Only MIPS. The candidate is never a verdict:
the judge decides.
"""
import re

from .c_scan import close, enclosing_block, header_before, normal, own_loop_statements
from .csource import _blank, find

FAMILY = 'loop_entry_reload'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_DO = re.compile(r'\bdo\s*\{')
_WHILE = re.compile(r'\s*while\s*\(\s*([^;{}]+?)\s*\)\s*;')
_CONSTANT = rf'{_ID}\s*=\s*-?\w+\s*;'
_READ = re.compile(r'^(?:\*\s*\(?\s*\w+\s*\)?|\w+\s*\[[^\]\n;]*\])$')


def _end_statements(clean, v, end):
    """(start of `v = E;`, E, [constant statements after it]) of the statements ending clean[:end], or None."""
    pattern = re.compile(rf'(?<![\w.>])({re.escape(v)}\s*=\s*([^;{{}}=]+?)\s*;)((?:\s*{_CONSTANT})*)\s*$')
    hit = pattern.search(clean, 0, end)
    if not hit or not _READ.match(hit[2].strip()) or re.search(r'\+\+|--|\w\s*\(', hit[2]):
        return None
    return hit.start(1), hit[2].strip(), re.findall(_CONSTANT, hit[3])


def _unguarded(clean, source, before):
    """The text of the statements before the loop with an identical-arm `if (c) { S } else { S }` replaced by S:
    (start, end, statements) of the guard, or None when the loop follows plain statements."""
    stop = len(clean[:before].rstrip())
    if clean[stop - 1:stop] != '}':
        return None
    else_open = _opener(clean, stop - 1)
    if else_open < 0 or not re.search(r'\belse\s*$', clean[:else_open]):
        return None
    if_close = clean[:else_open].rstrip()[:-4].rstrip()
    if if_close[-1:] != '}':
        return None
    if_open = _opener(clean, len(if_close) - 1)
    if if_open < 0 or not re.search(r'\bif\s*\([^;{}]*\)\s*$', clean[:if_open]):
        return None
    first, second = clean[if_open + 1:len(if_close) - 1], clean[else_open + 1:stop - 1]
    if normal(first) != normal(second):
        return None
    start = re.search(r'\bif\s*\([^;{}]*\)\s*$', clean[:if_open]).start()
    return start, stop, source[if_open + 1:len(if_close) - 1]


def _python_opener(clean, closing):
    depth = 0
    for i in range(closing, -1, -1):
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            depth -= 1
            if depth == 0:
                return i
    return -1


_opener = _python_opener
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _opener(clean, closing):
        found = _scan.open_if(clean, closing, '{', '}', -1)
        return _python_opener(clean, closing) if found is NotImplemented else found


def _proved(clean, loop_start, lo, v, expr):
    """True when the test `expr != 0` is taken the first time: an enclosing `if (G != 0)` for `p = G;`, or an enclosing
    `if (v != 0)`."""
    block = enclosing_block(clean, loop_start, lo)
    while block >= 0:
        header = header_before(clean, block)
        hit = re.fullmatch(r'if\s*\(\s*(.+?)\s*\)', header, re.S)
        if hit:
            cond = re.sub(r'\s*!=\s*0$', '', hit[1].strip()).strip()
            if cond == v:
                return True
            pointer = re.fullmatch(r'\*\s*\(?\s*(\w+)\s*\)?', expr)
            if pointer:
                for base in re.findall(rf'\b{pointer[1]}\s*=\s*(&?\s*\w+)\s*;', clean[lo:block]):
                    base = base.strip()
                    if cond in (f'{base}[0]', f'*{base}', f'*({base})') or (base.startswith('&') and cond == base[1:].strip()):
                        return True
        block = enclosing_block(clean, block, lo)
    return False


_WHILE_HEAD = re.compile(r'\bwhile\s*\(')


def _top_of_while(source, clean, opening, end):
    """`X...; while (c) { ...; X... }` with X constant assignments and nothing after the loop reading them, as
    `while (c) { X...; ... }`: the form the do-while child above also gives, for a loop already written as a while."""
    out = []
    for hit in _WHILE_HEAD.finditer(clean, opening, end):
        head_close = close(clean, hit.end() - 1, '(', ')')
        brace = re.compile(r'\s*\{').match(clean, head_close + 1)
        if head_close < 0 or not brace or re.search(r'\bdo\s*$', clean[:hit.start()]):
            continue
        body_open = brace.end() - 1
        body_close = close(clean, body_open)
        if body_close < 0 or own_loop_statements(clean, body_open + 1, body_close, 'continue'):
            continue
        tail = re.search(rf'((?:\s*{_CONSTANT})+)\s*$', clean[body_open + 1:body_close])
        pre = re.search(rf'((?:{_CONSTANT}\s*)+)$', clean[:hit.start()])
        if not tail or not pre:
            continue
        wanted = [normal(c) for c in re.findall(_CONSTANT, tail[1])]
        before = list(re.finditer(_CONSTANT, pre[1]))[-len(wanted):]
        if [normal(c.group()) for c in before] != wanted:
            continue
        names = [c.split('=')[0].strip() for c in wanted]
        if any(re.search(rf'(?<![\w.>]){re.escape(n)}\b', clean[body_close:end]) for n in names):
            continue
        indent = re.search(r'([ \t]*)$', source[:hit.start()])[1]
        inner = indent + '  '
        top = ''.join(f'{inner}{c}\n' for c in re.findall(_CONSTANT, source[body_open + 1 + tail.start(1):body_open + 1 + tail.end(1)]))
        start = pre.start(1) + before[0].start()
        out.append(source[:start] + source[hit.start():body_open + 1] + '\n' + top
                   + source[body_open + 1:body_open + 1 + tail.start(1)].strip('\n') + '\n' + indent + source[body_close:])
    return out


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    out = []
    for hit in _DO.finditer(clean, opening, span[1]):
        body_open = hit.end() - 1
        body_close = close(clean, body_open)
        tail = _WHILE.match(clean, body_close + 1) if body_close > 0 else None
        if not tail:
            continue
        cond = re.fullmatch(rf'({_ID})(?:\s*!=\s*0)?', tail[1].strip())
        if not cond or own_loop_statements(clean, body_open + 1, body_close, 'continue'):
            continue
        v = cond[1]
        end = _end_statements(clean, v, body_close)
        if not end or end[0] < body_open:
            continue
        end_at, expr, constants = end
        guard = _unguarded(clean, source, hit.start())
        before = _end_statements(clean, v, len(clean[:hit.start()].rstrip()) if not guard else guard[1])
        if guard:
            before = _end_statements(_blank(guard[2]), v, len(guard[2].rstrip()))
            if not before:
                continue
            start = guard[0]
        elif before:
            start = before[0]
        else:
            continue
        if before[1] != expr or [normal(c) for c in before[2]] != [normal(c) for c in constants]:
            continue
        if not _proved(clean, start, opening, v, expr):
            continue
        indent = re.search(r'([ \t]*)$', source[:hit.start()])[1]
        inner = indent + '  '
        body = source[body_open + 1:end_at].rstrip()
        parts = [indent + c.strip() for c in constants] if constants else []
        text = ''.join(f'{p}\n' for p in parts)
        text = text[len(indent):] if parts else ''
        loop = (f'{indent}while ({expr} != 0)\n{indent}{{\n{inner}{v} = {expr};\n{body}\n'
                + ''.join(f'{inner}{c.strip()}\n' for c in constants) + f'{indent}}}')
        out.append((FAMILY, source[:start] + text + loop + source[tail.end():]))
        if constants and not any(re.search(rf'(?<![\w.>]){re.escape(c.split("=")[0].strip())}\b', clean[tail.end():span[1]])
                                 for c in constants):
            top = ''.join(f'{inner}{c.strip()}\n' for c in constants)
            loop = f'{indent}while ({expr} != 0)\n{indent}{{\n{top}{inner}{v} = {expr};\n{body}\n{indent}}}'
            out.append((FAMILY, source[:start] + loop + source[tail.end():]))
    out += [(FAMILY, text) for text in _top_of_while(source, clean, opening, span[1])]
    return [x for x in out if x[1] != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
