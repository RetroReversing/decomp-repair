"""A pointer the target tests twice: `if (p != NULL || late) { if (p != NULL) {..} .. }`, the second test on a copy.

The game's source asks a call's result twice: once to enter the work (`found != NULL || timer > 300`) and again to skip
the part that needs the object. The target keeps both tests (`bnez $a0` into the body, then after the timer's `slti` a
`beqz $a0` over the body). m2c drops the second one, since it knows the pointer is null on that path, and writes two
entries into one join (`goto found; if (..) goto tail; v = 0; goto join; found: BODY; v = 0; join: ..`). Writing the
`||` with the retest is not enough either: with one variable the compiler (KMC GCC 2.7.2 and SN GCC, -O2) folds the
retest into a jump. A second local assigned from the call, read only by the retest, keeps it. A KMC / SN GCC 61
instruction function went 560 -> 0 with the three edits below; each of the first two alone left it at 560 or 305. That
the copy keeps the retest because the passes that fold it do not know the two pseudos are equal is a hypothesis; the
judge decides.

guard_retest_copy
    `T = f(..);`, a later `if (T != NULL || ..) {` whose body holds `if (T != NULL) {`: one child declares `T_copy`, writes
    `T_copy = T;` after the call and makes the inner test read it. Everything else keeps reading T.

skip_body_join_retest
    m2c's two entries into one join, with `V = 0;` in both: written as `if (P != NULL || !(C)) { if (P != NULL) { BODY }
    V = 0; REST } else { TAIL }`. Children: with the retest on a copy and the empty counter loop as a `for`, with the
    copy alone, and without the copy.

empty_counter_for
    `V = 0; V++; while (V < K) { V++; }`, or the same as m2c's `label: if (V < K) { V++; goto label; }`: the delay loop
    `for (V = 0; V < K; V++) {}`."""
import re

from .clean_rewrite import negate
from .csource import _blank, find
from .integer_repair_support import IDENT
from .pattern_repairs import close

COPY = 'guard_retest_copy'
JOIN = 'skip_body_join_retest'
EMPTY = 'empty_counter_for'
FAMILIES = (JOIN, COPY, EMPTY)
LIMIT = 4

_NULL = r'(?:NULL|0)'
_CALL = re.compile(rf'(?<![\w.>])(?P<var>{IDENT})\s*=\s*{IDENT}\s*\([^;{{}}]*\)\s*;')
_LOOP = re.compile(
    rf'(?<![\w.>])(?P<v>{IDENT})\s*=\s*0\s*;\s*(?P=v)\s*(?:\+\+|\+=\s*1)\s*;\s*(?:'
    rf'while\s*\(\s*(?P=v)\s*<\s*(?P<a>\w+)\s*\)\s*\{{\s*(?P=v)\s*(?:\+\+|\+=\s*1)\s*;\s*\}}|'
    rf'(?P<label>{IDENT})\s*:\s*;?\s*if\s*\(\s*(?P=v)\s*<\s*(?P<b>\w+)\s*\)\s*\{{\s*(?P=v)\s*(?:\+\+|\+=\s*1)\s*;\s*'
    rf'goto\s+(?P=label)\s*;\s*\}})')
_ENTRY = re.compile(
    rf'\bif\s*\(\s*(?P<ptr>{IDENT})(?:\s*!=\s*{_NULL})?\s*\)\s*\{{\s*goto\s+(?P<found>{IDENT})\s*;\s*\}}\s*'
    rf'if\s*\((?P<cond>[^{{}};]*)\)\s*\{{\s*goto\s+(?P<tail>{IDENT})\s*;\s*\}}\s*'
    rf'(?P<v>{IDENT})\s*=\s*0\s*;\s*goto\s+(?P<join>{IDENT})\s*;\s*(?P=found)\s*:[ \t]*;?')


def _declaration(clean, opening, stop, var):
    return re.compile(rf'(?m)^[ \t]*(?P<type>[A-Za-z_][\w \t]*?\*)[ \t]*{var}[ \t]*;[ \t]*\n').search(clean, opening, stop)


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    return (clean, opening, span[1]) if opening >= 0 else None


def _indent(source, at):
    return re.match(r'[ \t]*', source[source.rfind('\n', 0, at) + 1:])[0]


def _with_copy(source, name, var, retest):
    """`source` with `var_copy` declared after `var`, set after the call that sets `var`, and read at `retest` (a regex
    that finds the retest's pointer as group `p`). None when the pieces are not all there."""
    found = _body(source, name)
    if not found:
        return None
    clean, opening, stop = found
    declared = _declaration(clean, opening, stop, var)
    call = next((c for c in _CALL.finditer(clean, opening, stop) if c['var'] == var), None)
    copy = f'{var}_copy'
    if not declared or not call or re.search(rf'\b{copy}\b', clean):
        return None
    again = retest.search(clean, call.end(), stop)
    if not again:
        return None
    kind = re.sub(r'\s+', ' ', declared['type'].strip())
    text = source[:again.start('p')] + copy + source[again.end('p'):]
    text = text[:call.end()] + f'\n{_indent(source, call.start())}{copy} = {var};' + text[call.end():]
    return text[:declared.end()] + f'{_indent(source, declared.start())}{kind}{copy};\n' + text[declared.end():]


def _copy_children(source, name):
    found = _body(source, name)
    if not found:
        return []
    clean, opening, stop = found
    out = []
    for call in _CALL.finditer(clean, opening, stop):
        var = call['var']
        outer = re.compile(rf'\bif\s*\(\s*{var}(?:\s*!=\s*{_NULL})?\s*\|\|').search(clean, call.end(), stop)
        if not outer:
            continue
        brace = clean.find('{', outer.end(), stop)
        end = close(clean, brace, '{', '}') if brace >= 0 else None
        if not end:
            continue
        retest = re.compile(rf'\bif\s*\(\s*(?P<p>{var})(?:\s*!=\s*{_NULL})?\s*\)\s*\{{')
        if not retest.search(clean, brace, end):
            continue
        # search from the outer brace, so the outer test itself is never the one rewritten
        child = _with_copy(source, name, var, re.compile(rf'\|\|(?s:.)*?\{{(?s:.)*?{retest.pattern}'))
        if child:
            out.append(child)
    return out


def _loop_children(source, name):
    found = _body(source, name)
    if not found:
        return []
    clean, opening, stop = found
    out = []
    for loop in _LOOP.finditer(clean, opening, stop):
        label = loop['label']
        if label and len(re.findall(rf'\bgoto\s+{label}\b', clean)) != 1:
            continue
        v, bound = loop['v'], loop['a'] or loop['b']
        pad = _indent(source, loop.start())
        text = f'for ({v} = 0; {v} < {bound}; {v}++) {{\n{pad}}}'
        out.append(source[:loop.start()] + text + source[loop.end():])
    return out


def _join_children(source, name):
    found = _body(source, name)
    if not found:
        return []
    clean, opening, stop = found
    entry = _ENTRY.search(clean, opening, stop)
    if not entry:
        return []
    ptr, v, join, tail = entry['ptr'], entry['v'], entry['join'], entry['tail']
    second = re.compile(rf'(?<![\w.>]){v}\s*=\s*0\s*;\s*{join}\s*:[ \t]*;?').search(clean, entry.end(), stop)
    if not second:
        return []
    leave = re.compile(rf'(?:goto\s+(?P<end>{IDENT})|return)\s*;\s*{tail}\s*:[ \t]*;?').search(clean, second.end(), stop)
    if not leave:
        return []
    finish = rf'{leave["end"]}\s*:\s*;?\s*(?:return\s*;\s*)?\}}' if leave['end'] else r'(?:return\s*;\s*)?\}'
    last = re.compile(finish).search(clean, leave.end(), stop)
    if not last or clean[last.end():stop].strip():
        return []
    labels = [entry['found'], join, tail] + ([leave['end']] if leave['end'] else [])
    if any(len(re.findall(rf'\bgoto\s+{label}\b', clean[opening:stop])) != 1 for label in labels):
        return []
    parts = (source[entry.end():second.start()], source[second.end():leave.start()], source[leave.end():last.start()])
    body, rest, other = (part.strip('\n').rstrip() for part in parts)
    # each part must stand alone as the inside of a block
    if any(_blank(part).count('{') != _blank(part).count('}') for part in parts) or re.search(r'(?m)^\s*\w+\s*:', _blank(body)):
        return []
    cond = source[entry.start('cond'):entry.end('cond')].strip()
    pad = _indent(source, entry.start()) or '    '

    def deeper(text, steps=1):
        return '\n'.join(('    ' * steps + line) if line.strip() else '' for line in text.split('\n'))

    block = (f'if ({ptr} != NULL || {negate(cond)}) {{\n'
             f'{pad}    if ({ptr} != NULL) {{\n{deeper(body, 2)}\n{pad}    }}\n'
             f'{pad}    {v} = 0;\n{deeper(rest)}\n'
             f'{pad}}} else {{\n{deeper(other)}\n{pad}}}\n')
    plain = source[:entry.start()] + block + source[last.end() - 1:]
    out = []
    for copied in _copy_children(plain, name):
        out += _loop_children(copied, name)[:1] + [copied]
    return out + [plain]


def variants(source, name):
    joined = [(JOIN, child) for child in _join_children(source, name)]
    copies = [(COPY, child) for child in _copy_children(source, name)]
    loops = [(EMPTY, child) for child in _loop_children(source, name)]
    return joined[:LIMIT] + copies[:LIMIT] + loops[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
