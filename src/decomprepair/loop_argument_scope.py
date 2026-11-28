"""Statements of an innermost loop in blocks of their own, with some arguments held in locals of the block.

Matched on an SN GCC 2.8.1 (`-O2 -G0 -mips3`) tiled background draw, 10 -> 0 on the exact judge. The loop body was two
display-list macros, and the only rows left were one hoisted opcode word built in `$v0` where the target builds it in the
reload register (`lui $s7, 0xf400`), that is, a constant the outer loop's pass moved out and the allocator then gave no
register. loop.c (`move_movables`, read in the 2.8.1 source) moves a constant when `threshold * savings * lifetime >=
insn_count`, and the dumps showed it short by a few: the lifetime grew with the inner loop's span while the insn count
did not when each statement sat in a block declaring a local:

    { void *image = gImage; draw(gfx++, image, x, y); }
    { s32 s = x << 5; s32 t = y << 5; rect(gfx++, x * 4, y * 4, s, t); }

Either block alone left the score at 10; both together reached 0. That the block notes are what lengthens the lifetime
is measured from the `-dL` dumps (125 to 135 with four nested blocks), not proved from the source.

loop_argument_scope
    For the plain call statements (functions or macros) directly inside a loop that holds no other loop: hold in locals
    of a new block either the arguments that are exactly an `extern` scalar or pointer of this file or header, or the
    arguments that are a shift of a local or parameter by a literal, or both. One child per statement and kind, one per
    pair of statements and one with every statement, each of those two holding both kinds.

The held values are read before the statement instead of inside it. A statement that assigns or steps the same name in
any argument is left alone. The exact judge decides every child.
"""
import itertools
import re

from .call_global_stage import plain_calls
from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'loop_argument_scope'
FAMILIES = (FAMILY,)
LIMIT = 6
_TYPE = r'(?:(?:unsigned|signed)\s+)?(?!return\b|goto\b|else\b|volatile\b|extern\b|typedef\b){0}'.format(IDENT)
_EXTERN = re.compile(rf'\bextern\s+(?P<type>{_TYPE})(?P<stars>[\s*]+)(?P<name>{IDENT})\s*;')
_DECLARED = re.compile(rf'(?<![\w.>])(?P<type>{_TYPE})(?:\s+|\s*\*[\s*]*)(?P<name>{IDENT})\s*(?=[;=,)])')
_SHIFT = re.compile(rf'\s*(?P<name>{IDENT})\s*(?:<<|>>)\s*(?:0[xX][0-9A-Fa-f]+|\d+)\s*')


def _loop_bodies(part):
    """[(opening brace, closing brace)] of the loop bodies of the function that hold no loop."""
    clean = part.clean
    found = []
    for hit in re.finditer(r'\b(?:(?P<head>while|for)\s*\(|do\s*\{)', clean[part.opening:part.end]):
        at = part.opening + hit.end() - 1
        if hit['head']:
            depth = 0
            while at < part.end:
                depth += clean[at] == '('
                depth -= clean[at] == ')'
                if not depth:
                    break
                at += 1
            brace = re.compile(r'\s*\{').match(clean, at + 1)
            if not brace:
                continue
            at = brace.end() - 1
        depth, close = 0, at
        while close < part.end:
            depth += clean[close] == '{'
            depth -= clean[close] == '}'
            if not depth:
                break
            close += 1
        found.append((at, close))
    return [(a, b) for a, b in found if not any(a < c and d < b for c, d in found)]


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    bodies = _loop_bodies(part)
    if not bodies:
        return []
    externs = {hit['name']: ' '.join((hit['type'] + ' ' + hit['stars']).split())
               for text in (header, source) for hit in _EXTERN.finditer(text)}
    own = find(source, name)[0]  # from the function's own head: its parameters and locals, not the file's externs
    declared = {hit['name']: ' '.join(hit['type'].split()) for hit in _DECLARED.finditer(part.clean[own:part.end])}
    taken = set(re.findall(IDENT, source + header))
    statements = []
    for start, end, _, spans in plain_calls(part):
        if not any(a < start < b for a, b in bodies):
            continue
        arguments = [part.clean[a:b] for a, b in spans]
        written = set()
        for argument in arguments:
            written.update(re.findall(rf'({IDENT})\s*(?:\+\+|--|(?:<<|>>|[-+*/%&|^])?=(?!=))', argument))
            written.update(re.findall(rf'(?:\+\+|--)\s*({IDENT})', argument))
        held = {'global': [], 'shift': []}
        for (a, b), argument in zip(spans, arguments):
            word = argument.strip()
            shift = _SHIFT.fullmatch(argument)
            if word in externs and word not in written and word not in declared:
                held['global'].append((a, b, externs[word], f'{word}_held'))
            elif shift and shift['name'] in declared and shift['name'] not in written:
                held['shift'].append((a, b, declared[shift['name']], f"{shift['name']}_shift"))
        if held['global'] or held['shift']:
            statements.append((start, end + 2, held))
    statements = statements[:LIMIT]

    def scoped(items):
        changes, used = [], set(taken)
        for start, end, arguments in items:
            first = source.rfind('\n', 0, start) + 1
            indent = source[first:start] if not source[first:start].strip() else ''
            lines = ''
            for a, b, kind, base in arguments:
                fresh, count = base, 2
                while fresh in used:
                    fresh, count = f'{base}{count}', count + 1
                used.add(fresh)
                gap = '' if kind.endswith('*') else ' '
                lines += f'{indent}    {kind}{gap}{fresh} = {source[a:b].strip()};\n'
                lead = source[a:b][:len(source[a:b]) - len(source[a:b].lstrip())]
                changes.append((a, b, lead + fresh))
            changes.append((start, start, '{\n' + lines + indent + '    '))
            changes.append((end, end, '\n' + indent + '}'))
        return edit(source, changes)

    def both(item):
        start, end, held = item
        return start, end, sorted(held['global'] + held['shift'])

    children = []
    if len(statements) > 1:
        children.append(scoped([both(item) for item in statements]))
    if len(statements) > 2:
        children += [scoped([both(a), both(b)]) for a, b in itertools.combinations(statements, 2)]
    for item in statements:
        start, end, held = item
        if held['global'] and held['shift']:
            children.append(scoped([both(item)]))
        children += [scoped([(start, end, held[kind])]) for kind in ('global', 'shift') if held[kind]]
    return [(FAMILY, text) for text in dict.fromkeys(children) if text]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
