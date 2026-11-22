"""Reuse dead float holders when an earlier projection keeps zero live."""

import re
from dataclasses import replace

from .call_lifetime_repairs import block_path
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .local_flow import Flow
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible
from .pattern_repairs import close

FAMILY = 'phase_projection_holders'
DEFERRED = 'phase_projection_holders_deferred_init'
_FREG = r'\$f\d+'
_WORD = r'\$[a-z][a-z0-9]*'
_SLOT = re.compile(rf'(?m)^[ \t]*volatile\s+float\s+(?P<slot>{IDENT})\s*;\s*}}\s*(?P<frame>{IDENT})\s*;')
_SAMPLE = re.compile(
    rf'(?m)^[ \t]*(?P<axis>{IDENT})\s*=\s*\*\(\(f32\s*\*\)\s*\(\(\(char\s*\*\)'
    rf'\s*{IDENT}\)\s*\+\s*(?P<offset>{NUMBER})\)\s*\)\s*;'
)
_PAIR = re.compile(
    rf'(?m)^[ \t]*(?P<x>{IDENT})\s*(?P<sum>=\s*0\.0[fF]\s*\+)\s*'
    rf'\(\s*(?P<axis>{IDENT})\s*\*\s*(?P<xc>{IDENT})\((?P<arg>[^;{{}}\n]+)\)\s*\)\s*;\s*'
    rf'(?P<z>{IDENT})\s*\+=\s*\(\s*(?P=axis)\s*\*\s*(?P<zc>{IDENT})\((?P=arg)\)\s*\)\s*;\s*'
    rf'\*[^;{{}}\n]+\s*=\s*(?P=axis)\s*;\s*'
    rf'(?P<value>{IDENT})\s*=\s*(?P<abs>{IDENT})\(\s*(?P=axis)\s*\)\s*;'
)
_PREVIOUS_AXIS = re.compile(
    rf'(?m)^[ \t]*(?P<held>{IDENT})\s*=\s*(?P<sample>{IDENT})\([^;{{}}\n]+\)\s*;\s*'
    rf'(?P<magnitude>{IDENT})\s*=\s*(?P<abs>{IDENT})\(\s*(?P=held)\s*\)\s*;'
)
_GAIN = re.compile(
    rf'(?m)^[ \t]*{IDENT}\s*=\s*\(\(\s*(?P<held>{IDENT})\s*-\s*(?P<center>{IDENT})'
    rf'\s*\)\s*\*\s*(?P<gain>{IDENT})\s*\)\s*\+\s*(?P=center)\s*;'
)
_FLOAT_DECLARATION = re.compile(rf'(?m)^[ \t]*(?:f32|float)\s+(?P<name>{IDENT})\s*;')
_CONTROL = re.compile(rf'(?m)^[ \t]*(?!(?:case|default)\b){IDENT}\s*:(?!:)|\bgoto\b')


def _witnesses(rows):
    linked = [(expected, actual) for _, expected, actual in rows if expected]
    for pos, (expected, actual) in enumerate(linked):
        load = re.fullmatch(rf'lwc1 ({_FREG}), ({NUMBER})(\({_WORD}\))', expected)
        other = re.fullmatch(rf'lwc1 ({_FREG}), ({NUMBER})(\({_WORD}\))', actual)
        if not load or not other or load[1] == other[1] or load.groups()[1:] != other.groups()[1:]:
            continue
        region = linked[pos + 1:pos + 67]
        calls = [(i, match[1]) for i, (a, b) in enumerate(region, pos + 1)
                 if a == b and (match := re.fullmatch(rf'jal ({IDENT})', a))]
        if len(calls) < 4:
            continue
        # The established phase holder is live through both projections and
        # the absolute call. The old literal uses a separate saved FPR.
        projections = [(a, b) for a, b in region[:45] if a == f'mul.s $f0, {load[1]}, $f0'
                       and b == f'mul.s $f0, {other[1]}, $f0']
        capture = next((re.fullmatch(rf'mov\.s ({_FREG}), \$f0', a) for a, b in region[:55]
                        if a != b and b == f'mov.s {other[1]}, $f0'
                        and re.fullmatch(rf'mov\.s ({_FREG}), \$f0', a)), None)
        if len(projections) != 2 or not capture or not any(
            re.fullmatch(rf'mtc1 {_WORD}, \$f16', a) and b == f'mtc1 $zero, {capture[1]}' for a, b in region[:45]
        ):
            continue
        gain = any(a == b and re.fullmatch(rf'mul\.s {_FREG}, {_FREG}, {re.escape(capture[1])}', a)
                   for a, b in linked[max(0, pos - 100):pos])
        if not gain:
            continue
        zeros = []
        for i, (a, b) in enumerate(linked[pos + 45:pos + 130], pos + 45):
            zero = re.fullmatch(rf'mtc1 \$zero, ({_FREG})', a)
            store = re.fullmatch(rf'swc1 {re.escape(capture[1])}, (.+\(\$sp\))', b)
            if (zero and store and i + 1 < len(linked)
                    and linked[i + 1] == ('nop', f'lwc1 {zero[1]}, {store[1]}')):
                zeros.append((i, zero[1], store[1]))
        if (len(zeros) == 2 and zeros[0][1] != '$f0' and zeros[1][1] == '$f0' and zeros[0][2] == zeros[1][2]
                and zeros[1][0] - zeros[0][0] < 65):
            before_zero = [callee for i, callee in calls if i < zeros[0][0]]
            if len(before_zero) >= 4:
                yield (*before_zero[:3], before_zero[-1], integer(load[2]))


def _staged_zero(part, slot, start, value, probe):
    field = rf'{slot["frame"]}\s*\.\s*{slot["slot"]}'
    assignment = rf'{field}\s*=\s*0\.0[fF]\s*;'
    test = re.compile(
        rf'(?m)^[ \t]*{assignment}[ \t]*\n[ \t]*'
        rf'if\s*\(\s*!\(\s*{value}\s*>\s*(?P<testing>{field})\s*\)\s*\)'
    )
    fallback = re.compile(
        rf'(?m)^[ \t]*{assignment}[ \t]*\n[ \t]*(?P<output>{IDENT})\s*=\s*(?P<reading>{field})\s*;'
    )
    head = list(fallback.finditer(part.clean, start, min(part.end, start + 1400)))
    tail = list(test.finditer(part.clean, start, min(part.end, start + 3800)))
    if len(head) != 1 or len(tail) != 1 or head[0].end() >= tail[0].start():
        return None
    before = part.clean[start:head[0].start()]
    if not re.search(rf'\bif\s*\(\s*{probe}\(', before):
        return None
    return head[0], tail[0]


def _holds_reusable(part, sample, pair, init, held, gain, old_read):
    # Ignore just the read that moves to the new magnitude holder. All other
    # reads of the old value still have to follow their original assignments.
    clean = part.clean
    revised = edit(clean, [(*old_read, '0'.ljust(old_read[1] - old_read[0]))])
    proof = replace(part, clean=revised)
    names = {held, gain, pair['x'], pair['value']}
    declarations = [match for match in _FLOAT_DECLARATION.finditer(revised, part.opening + 1, part.end)
                    if match['name'] in names]
    if {match['name'] for match in declarations} != names or len(declarations) != len(names):
        return False
    try:
        flow = Flow(proof, declarations)
    except (ValueError, RecursionError):
        return False
    capture = flow.at(pair.start('value'))
    first = flow.at(init.end() - 1)
    projection = flow.at(pair.start('x'))
    if (not capture or not first or not projection
            or not flow.dead(held, sample.start('axis')) or gain in capture.live
            or any(pair['value'] in flow.nodes[i].live for i in capture.successors)):
        return False
    # The accumulator's zero assignment must dominate its former literal use.
    target = flow.nodes.index(projection)
    blocker = flow.nodes.index(first)
    pending, seen = [flow.entry], {blocker}
    while pending:
        index = pending.pop()
        if index in seen:
            continue
        if index == target:
            return False
        seen.add(index)
        pending.extend(flow.nodes[index].successors - seen)
    return True


def _first_initializer(part, pair, locals_by_name):
    x = pair['x']
    matches = list(re.finditer(rf'(?m)^[ \t]*{x}\s*=\s*0\.0[fF]\s*;', part.clean[:pair.start()]))
    if len(matches) != 1:
        return None
    start = matches[0]
    prefix = block_path(part, start.start())
    if (not _in_scope(part, locals_by_name[x][1], start.start())
            or block_path(part, pair.start())[:len(prefix)] != prefix
            or re.search(rf'\b{x}\b', part.clean[start.end():pair.start()])):
        return None
    segment = part.clean[start.end():pair.start()]
    if _CONTROL.search(segment) or len(re.findall(r'\bswitch\s*\(', segment)) != 1:
        return None
    return start


def _deferred_initializer(part, init):
    stop = part.clean.find('\n', init.end()) + 1
    guard = re.match(r'[ \t]*if\s*\(\s*' + IDENT + r'\s*!=\s*0\s*\)\s*{', part.clean[stop:])
    if not stop or not guard:
        return None
    end = close(part.clean, stop + guard.end() - 1, '{', '}')
    if not end or _CONTROL.search(part.clean[stop:end]) or re.match(r'\s*else\b', part.clean[end:]):
        return None
    return end + 1 if part.clean[end:end + 1] == '\n' else None


def variants(source, name, rows, *, header='', max_bytes=65536):
    witnesses = set(_witnesses(rows))
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    if (re.search(r'(?m)^\s*#\s*pragma\s+STDC\s+FENV_ACCESS\s+ON', context)
            or any(' '.join(typ.split()) != 'float'
                   for typ in re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context))):
        return []
    slots = list(_SLOT.finditer(part.clean, part.opening + 1, part.end))
    if len(slots) != 1 or len(re.findall(rf'\b{slots[0]["slot"]}\b', part.body)) != 5:
        return []
    slot = slots[0]
    if re.search(rf'\b{slot["frame"]}\b(?!\s*\.)', part.clean[slot.end():part.end]):
        return []
    macros = set(re.findall(rf'(?m)^\s*#\s*(?:define|undef)\s+({IDENT})', context))
    local = _typed_locals(part, r'(?:f32|float)')
    proposals = []
    for pair in _PAIR.finditer(part.clean, part.opening + 1, part.end):
        samples = [m for m in _SAMPLE.finditer(part.clean, max(part.opening + 1, pair.start() - 900), pair.start())
                   if m['axis'] == pair['axis'] and block_path(part, m.start()) == block_path(part, pair.start())]
        if len(samples) != 1:
            continue
        sample = samples[0]
        callees = tuple(pair[n] for n in ('xc', 'zc', 'abs'))
        probes = {probe for *names, probe, offset in witnesses
                  if tuple(names) == callees and offset == integer(sample['offset'])}
        if len(probes) != 1:
            continue
        prior = [m for m in _PREVIOUS_AXIS.finditer(part.clean, max(part.opening + 1, sample.start() - 4200),
                                                   sample.start())
                 if m['abs'] == pair['abs'] and block_path(part, m.start()) == block_path(part, pair.start())]
        if len(prior) != 1:
            continue
        held, magnitude = prior[0]['held'], prior[0]['magnitude']
        gains = [m for m in _GAIN.finditer(part.clean, prior[0].end(), sample.start()) if m['held'] == held]
        zeroes = _staged_zero(part, slot, pair.end(), magnitude, next(iter(probes)))
        if len(gains) != 1 or not zeroes:
            continue
        gain = gains[0]
        fallback, test = zeroes
        scope = (sample.start(), pair.end())
        names = {pair['axis'], pair['x'], pair['z'], pair['value'], gain['gain'], held, magnitude, fallback['output']}
        if (len(names) != 8 or macros & (names | {slot['slot'], slot['frame'], 'f32', pair['abs'], pair['xc'], pair['zc']})
                or any(v not in local or not _in_scope(part, local[v][1], sample.start()) or _escaped(part.body, v)
                       for v in names)
                or re.search(rf'\b(?:volatile|const)\s+(?:f32|float)\s+[^;]*\b(?:{"|".join(sorted(names))})\b',
                             part.body)
                or len(re.findall(rf'\b{pair["axis"]}\b', part.body)) != 8
                or _CONTROL.search(part.clean[gain.end():test.end()])):
            continue
        use = re.search(rf'\b{fallback["output"]}\s*=\s*(?P<magnitude>{pair["value"]})\s*\*\s*'
                        r'\d+\.\d+[fF]\s*;', part.clean[fallback.end():test.start()])
        if not use or re.search(rf'\b{gain["gain"]}\b', part.clean[gain.end():test.end()]):
            continue
        init = _first_initializer(part, pair, local)
        magnitude_span = tuple(fallback.end() + i for i in use.span('magnitude'))
        if not init or not _holds_reusable(part, sample, pair, init, held, gain['gain'], magnitude_span):
            continue
        valid_length = len(re.findall(rf'\b{pair["axis"]}\b', part.clean[slice(*scope)])) == 7
        if not valid_length:
            continue
        changes = [(scope[0] + match.start(), scope[0] + match.end(), held)
                   for match in re.finditer(rf'\b{pair["axis"]}\b', part.clean[slice(*scope)])]
        changes += [(*pair.span('sum'), '+='), (*pair.span('value'), gain['gain']),
                    (*magnitude_span, gain['gain'])]
        for stage, argument in ((fallback, 'reading'), (test, 'testing')):
            line = part.clean.find('\n', stage.start()) + 1
            changes.extend([(stage.start(), line, ''), (*stage.span(argument), '0.0f')])
        proposals.append((changes, init))
    if len(proposals) != 1:
        return []
    changes, init = proposals[0]
    candidates = [(FAMILY, edit(source, changes))]
    if (defer := _deferred_initializer(part, init)) is not None:
        end = part.clean.find('\n', init.end()) + 1
        move = [(init.start(), end, ''), (defer, defer, source[init.start():end])]
        candidates.append((DEFERRED, edit(source, changes + move)))
    return [(label, candidate) for label, candidate in candidates if len(candidate.encode()) <= max_bytes]
