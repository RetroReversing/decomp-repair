"""Where a one-step update is written: earlier than its use, or after the statement that indexed with the old value.

local_step_hoist
    `v--;` (`v++;`, `v += K;`, `v -= K;`) on a plain local moved up over the statements before it in the same block that
    never name `v`, one child per position, nearest first. A call argument `v - K` of a local that is not read after
    the call is offered the same way, as `v -= K;` at that position and `v` in the call. The game stepped the value
    before the work between: on an N64 sprite-drawing routine (SN GCC 2.8.1, `-G0 -mips3 -O2`) a `tex--;` written
    after the `if`/`else` that picks a scale, one statement too late, left the branch's delay slot empty (160 -> 0 when
    moved above it).

index_postinc_statement
    A statement that indexes with a post-incremented counter, `d = &a[n++];`, written as `d = &a[n];` and `n++;` after
    it. The same routine's matrix command loaded the index, stored the command word and only then wrote the new index
    back (450 -> 0 with the split; 610 with neither edit).

The compiler account of both is a hypothesis; the exact judge decides."""
import re

from .c_scan import _enclosing_block
from .integer_repair_support import IDENT, INTEGER, _address_taken, edit, split_args, view
from .pattern_repairs import close

FAMILY_HOIST = 'local_step_hoist'
FAMILY_SPLIT = 'index_postinc_statement'
FAMILIES = (FAMILY_HOIST, FAMILY_SPLIT)
LIMIT = 12
POSITIONS = 4
_STEP = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<text>(?P<var>{IDENT})\s*(?:\+\+|--|[-+]=\s*(?:0[xX][0-9a-fA-F]+|\d+))'
                   r'\s*;)[ \t]*\n')
_INDEXED = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<text>[^\n;{}]*\[\s*(?P<var>' + IDENT
                      + r')(?P<op>\+\+|--)\s*\][^\n;{}]*;)[ \t]*$')
_ARGUMENT = re.compile(rf'(?P<var>{IDENT})\s*(?P<op>[-+])\s*(?P<amount>0[xX][0-9a-fA-F]+|\d+)[uUlL]*')
_CALL = re.compile(rf'(?<![\w.>])(?P<callee>{IDENT})\s*\(')
_KEYWORDS = {'if', 'else', 'for', 'while', 'do', 'return', 'switch', 'case', 'sizeof'}
_PUNCTUATION = re.compile(r'[(){};]')
_LEAVES = re.compile(r'\b(?:return|goto|break|continue|case|default)\b|(?m:^[ \t]*\w+\s*:(?!:))')


def _local(part, name):
    """`name` is an integer local or parameter whose address is never taken."""
    declared = re.search(rf'(?<![\w.>]){INTEGER}\s+{name}\s*[;,=)]', part.clean[:part.end])
    return bool(declared) and not _address_taken(part.body, name)


def _boundaries(clean, opening, stop):
    """Offsets between `opening`'s brace and `stop` where a statement of that block starts."""
    found, braces, parens = [opening + 1], 0, 0
    for mark in _PUNCTUATION.finditer(clean, opening + 1, stop):
        char = mark.group(0)
        parens += (char == '(') - (char == ')')
        braces += (char == '{') - (char == '}')
        if char in ';}' and not braces and not parens and not re.match(r'\s*(?:else|while)\b', clean[mark.end():]):
            found.append(mark.end())
    return found


def _positions(source, part, statement, name):
    """Line starts above `statement` (an offset) that a step of `name` may move up to, nearest first."""
    clean = part.clean
    opening = _enclosing_block(clean, statement, part.opening)
    if opening is None or opening < part.opening:
        return []
    found = []
    for at in reversed(_boundaries(clean, opening, statement)):
        passed = clean[at:statement]
        if not passed.strip():
            continue
        if re.search(rf'(?<![\w.>]){name}\b', passed) or _LEAVES.search(passed):
            break
        line = source.find('\n', at) + 1
        if 0 < line <= statement and not source[at:line].strip():
            found.append(line)
    return found[:POSITIONS]


def _hoists(source, part):
    clean, out = part.clean, []
    for step in _STEP.finditer(clean, part.opening, part.end):
        name = step['var']
        if clean[:step.start()].rstrip()[-1:] not in (';', '{', '}') or not _local(part, name):
            continue
        line = step['indent'] + source[step.start('text'):step.end('text')] + '\n'
        for at in _positions(source, part, step.start(), name):
            out.append(edit(source, [(at, at, line), (step.start(), step.end(), '')]))
    if re.search(r'\b(?:for|while|do|goto)\b', part.body):
        return out
    for call in _CALL.finditer(clean, part.opening, part.end):
        end = close(clean, call.end() - 1)
        if call['callee'] in _KEYWORDS or not end:
            continue
        start = source.rfind('\n', 0, call.start()) + 1
        if clean[:start].rstrip()[-1:] not in (';', '{', '}'):
            continue
        for first, last in split_args(clean[call.end():end - 1]):
            text = clean[call.end() + first:call.end() + last]
            argument = _ARGUMENT.fullmatch(text.strip())
            if not argument:
                continue
            name = argument['var']
            if (not _local(part, name) or re.search(rf'(?<![\w.>]){name}\b', clean[end:part.end])
                    or len(re.findall(rf'(?<![\w.>]){name}\b', clean[start:end])) != 1):
                continue
            where = call.end() + first + len(text) - len(text.lstrip())
            indent = re.match(r'[ \t]*', source[start:])[0]
            line = f'{indent}{name} {argument["op"]}= {argument["amount"]};\n'
            for at in [start, *_positions(source, part, start, name)]:
                out.append(edit(source, [(at, at, line), (where, where + len(text.strip()), name)]))
    return out


def _splits(source, part):
    clean, out = part.clean, []
    for hit in _INDEXED.finditer(clean, part.opening, part.end):
        name, text = hit['var'], hit['text']
        if (clean[:hit.start()].rstrip()[-1:] not in (';', '{', '}') or not re.search(r'(?<![=!<>])=(?!=)', text)
                or len(re.findall(rf'(?<![\w.>]){name}\b', text)) != 1
                or any(c['callee'] not in _KEYWORDS for c in _CALL.finditer(text)) or re.match(r'\s*return\b', text)):
            continue
        operator = clean.index(hit['op'], hit.start('var') + len(name))
        out.append(edit(source, [(operator, operator + 2, ''),
                                 (hit.end('text'), hit.end('text'), f'\n{hit["indent"]}{name}{hit["op"]};')]))
    return out


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    out = [(FAMILY_SPLIT, child) for child in _splits(source, part)]
    out += [(FAMILY_HOIST, child) for child in _hoists(source, part)]
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',), 'order': 46}
