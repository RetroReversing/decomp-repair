"""Coalesce disjoint m2c float locals named for the same saved MIPS register.

Splitting one reused source local into separate float temporaries can change
KMC GCC's allocation order. A large N64 draft improved when names for a
saved FPR shared a declaration again, with each value still assigned on
entry to its own lifetime.
"""

import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .mips_returns import instructions
from .pattern_repairs import close

FAMILY = 'mips_float_local_reuse'
ACCUMULATOR_FAMILY = 'mips_float_accumulator_reuse'
ACROSS_CALL_FAMILY = 'saved_float_across_call'
FAMILIES = (FAMILY, ACCUMULATOR_FAMILY, ACROSS_CALL_FAMILY)
_DECLARATION = re.compile(
    r'(?m)^[ \t]*(?P<type>f32|float)[ \t]+'
    r'(?P<name>(?:temp|var)_(?:fs(?P<reg>[0-5])|s[0-7])(?:_\d+)?)[ \t]*;[ \t]*\n')
_LABEL = re.compile(r'(?m)(?:^|(?<=[;{}:]))\s*(?P<name>[A-Za-z_]\w*)\s*:(?!:)|\b(?:case\s+[^:{}]+|default\s*):')
_GOTO = re.compile(r'\bgoto\s+([A-Za-z_]\w*)\s*;')
_BRACE = re.compile(r'[{}]')


def _scopes(clean, start, end):
    opens = []
    scopes = []
    for brace in _BRACE.finditer(clean, start, end):
        if brace[0] == '{':
            opens.append(brace.start())
        elif opens:
            scopes.append((opens.pop(), brace.start()))
    return scopes


def _labels_enter_after_initializer(clean, start, stop, gotos):
    labels = list(_LABEL.finditer(clean, start, stop))
    return all(label['name'] not in (None, 'default')
               and gotos.get(label['name'])
               and all(start <= origin < stop for origin in gotos[label['name']])
               for label in labels)


def _lifetime(clean, decl, opening, end, scopes, gotos=None):
    name = decl['name']
    word = re.compile(rf'\b{name}\b')
    references = [hit for hit in word.finditer(clean, opening, end) if hit.start() != decl.start('name')]
    if not references or re.search(rf'&\s*\(*\s*{word.pattern}', clean[opening:end]):
        return None
    first, last = references[0], references[-1]
    if first.start() < decl.end() or clean[opening:first.start()].rstrip()[-1:] not in (';', '{', '}', ':'):
        return None
    initializer = re.match(r'\s*=(?!=)\s*([^;{}]+);', clean[first.end():end])
    if not initializer or word.search(initializer[1]):
        return None
    # The assignment must run before other references, including on subsequent
    # loop iterations. Reject uses outside this block and entries bypassing it.
    block = next(((start, stop) for start, stop in scopes if start < first.start() < stop), None)
    if not block or last.start() >= block[1]:
        return None
    if _LABEL.search(clean, first.end(), last.start()):
        if gotos is None or not _labels_enter_after_initializer(clean, first.end(), last.start(), gotos):
            return None
    if any(clean[opening:hit.start()].rstrip().endswith(('.', '->')) for hit in references):
        return None
    return (decl, references)


def _groups(lifetimes):
    groups = []
    for decl, refs in sorted(lifetimes, key=lambda life: life[1][0].start()):
        into = next((group for group in groups if group[-1][1][-1].end() < refs[0].start()), None)
        if into is None:
            groups.append([(decl, refs)])
        else:
            into.append((decl, refs))
    return [group for group in groups if len(group) >= 2]


def _rewrite(source, groups):
    edits = []
    for group in groups:
        if len(group) < 2:
            continue
        name = group[0][0]['name']
        for decl, refs in group[1:]:
            edits.append((decl.start(), decl.end(), ''))
            edits.extend((hit.start(), hit.end(), name) for hit in refs)
    return edit(source, edits)


def _accumulator_reuses(source, clean, opening, end, scopes, declarations):
    """Use a private accumulator earlier when no path observes its old value."""
    changes = []
    for name, decl in declarations.items():
        match = re.fullmatch(r'temp_s([0-7])(?:_\d+)?', name)
        dest = f'var_s{match[1]}' if match else None
        target = declarations.get(dest)
        if not target or target['type'] != decl['type']:
            continue
        life = _lifetime(clean, decl, opening, end, scopes)
        if not life or len(life[1]) != 2:
            continue
        first, use = life[1]
        before = max(clean.rfind(c, first.end(), use.start()) for c in ';{}') + 1
        consumer = re.match(rf'\s*(?P<dest>{dest})\s*=(?!=)\s*[^;{{}}]+;', clean[before:end])
        if not consumer or not before + consumer.start('dest') < use.start() < before + consumer.end():
            continue
        # A jump or conditional return could bypass the final assignment.
        # Calls cannot see a private local unless its address is taken.
        if re.search(r'\b(?:goto|break|continue|return)\b', clean[first.end():before]):
            continue
        refs = list(re.finditer(rf'\b{dest}\b', clean[first.end():before + consumer.end()]))
        if len(refs) != 1 or re.search(rf'&\s*\(*\s*{dest}\b', clean[opening:end]):
            continue
        first_scope = next((start for start, stop in scopes if start < first.start() < stop), None)
        use_scope = next((start for start, stop in scopes if start < use.start() < stop), None)
        if first_scope != use_scope:
            continue
        changes.append((dest, [(decl.start(), decl.end(), ''),
                               (first.start(), first.end(), dest), (use.start(), use.end(), dest)]))
    choices = [edit(source, edits) for _, edits in changes]
    if len(changes) > 1 and len({dest for dest, _ in changes}) == len(changes):
        choices.insert(0, edit(source, [change for _, edits in changes for change in edits]))
    return [(ACCUMULATOR_FAMILY, text) for text in choices[:4]]


_AFTER_DIFFERENCE = re.compile(rf'\s*=\s*(?P<expression>[^;{{}}]+);\s*{IDENT}\s*=\s*(?P<call>{IDENT})\s*\(')
_OFFSET = re.compile(r'\+\s*(0[xX][0-9a-fA-F]+|[0-9]+)\s*\)')
_LOAD_OFFSET = re.compile(r'lwc1\s+\$f\w+,\s*(0[xX][0-9a-fA-F]+|[0-9]+)\(\$\w+\)')


def _saved_difference(rows, call, saved, offsets):
    for i, row in enumerate(rows[:-1]):
        if row != f'jal {call}' or not re.match(rf'sub\.s\s+\$f{saved},', rows[i+1]):
            continue
        before = rows[max(0, i-14):i]
        loaded = {int(match[1], 0) for text in before if (match := _LOAD_OFFSET.fullmatch(text))}
        if offsets <= loaded and any(text.startswith('mul.s ') for text in before):
            return True
    return False


def _across_call_reuse(source, clean, lifetimes, asm):
    rows = instructions(asm) if asm else []
    if not rows:
        return []
    choices = []
    lives = [life for bank in lifetimes.values() for life in bank]
    for decl, refs in lives:
        init = _AFTER_DIFFERENCE.match(clean, refs[0].end())
        if not init or not all(token in init['expression'] for token in ('-', '*')):
            continue
        offsets = {int(match[1], 0) for match in _OFFSET.finditer(init['expression'])}
        if len(offsets) != 2 or not _saved_difference(rows, init['call'], 20+2*int(decl['reg']), offsets):
            continue
        earlier = [life for life in lives if life[0]['type'] == decl['type']
                   and life[0]['reg'] != decl['reg'] and life[1][-1].end() < refs[0].start()]
        earlier.sort(key=lambda life: -life[1][-1].end())
        choices.extend((ACROSS_CALL_FAMILY, _rewrite(source, [[life, (decl, refs)]])) for life in earlier[:4])
    return choices[:6]


def variants(source, name, asm=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'(?m)^\s*#|\b(?:asm|__asm__|setjmp|longjmp)\b|\bgoto\s*\*', clean[opening:end]):
        return []
    scopes = _scopes(clean, opening, end)
    declared = list(_DECLARATION.finditer(clean, opening, end))
    names = [decl['name'] for decl in declared]
    declarations = {}
    lifetimes = {}
    labelled_lifetimes = {}
    gotos = {}
    for jump in _GOTO.finditer(clean, opening, end):
        gotos.setdefault(jump[1], []).append(jump.start())
    for decl in declared:
        scope = next((start for start, stop in scopes if start < decl.start() < stop), None)
        if scope != opening or names.count(decl['name']) != 1:
            continue
        declarations[decl['name']] = decl
        if decl['reg'] is None:
            continue
        life = _lifetime(clean, decl, opening, end, scopes)
        bank = (decl['reg'], decl['type'])
        if life:
            lifetimes.setdefault(bank, []).append(life)
        elif life := _lifetime(clean, decl, opening, end, scopes, gotos):
            labelled_lifetimes.setdefault(bank, []).append(life)
    label_choices = []
    for bank, labelled in labelled_lifetimes.items():
        pool = lifetimes.get(bank, []) + labelled
        for life in labelled:
            # Try the nearest earlier value first. Grouping the entire bank
            # would also change unrelated register lifetimes.
            earlier = [other for other in pool if other[1][-1].end() < life[1][0].start()]
            if earlier:
                previous = max(earlier, key=lambda item: item[1][-1].end())
                label_choices.append(_rewrite(source, [[previous, life]]))
    groups = sorted((_groups(items) for items in lifetimes.values()), key=lambda bank: -sum(map(len, bank)))
    choices = []
    for bank in groups:
        if not bank:
            continue
        choices.append(_rewrite(source, bank))
        # Leave the earliest split temporary independent as an alternative.
        # Other lifetimes can reuse their storage without extending the first one.
        longest = max(bank, key=len)
        if len(longest) >= 3:
            choices.append(_rewrite(source, [longest[:1] + longest[2:] if group is longest else group for group in bank]))
    accumulators = _accumulator_reuses(source, clean, opening, end, scopes, declarations)
    across_calls = _across_call_reuse(source, clean, lifetimes, asm)
    return across_calls + accumulators + [(FAMILY, text) for text in dict.fromkeys(label_choices + choices) if text != source][:12]
