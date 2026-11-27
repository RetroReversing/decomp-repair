"""A constant multiple of one value that the compiler built in stages across branches, written back as one multiply.

The compiler turns `&records[i]` (a 0x68-byte record) into shifts and adds and moves the first steps into the delay
slots of the branches before the join, so m2c names each step a local: `two = i * 2;` in one arm, `three = i * 3;` in
another, `three = two + i;` at the join, then `((three * 4) + i) * 8`. The staged locals keep their own registers and
the match is far off. This family folds every such local back into `i * K` (only where every read is reached by an
assignment of the local made after the last change to `i`, so the program does not change) and folds the constants
(`i * 0x68`).

The same draft often reads a symbol-address local (`base = &D;`) in an arm its only assignment does not reach (a
search that cached the address set it before the first use): `base_set_every_arm` assigns it again at the head of the
arm that reads it, which is also what the target does when it loads the address a second time.

An N64 input handler built by SN GCC 2.8.1: 870 -> 200 (rejoin) -> 0 (base set in the second arm)."""
import re

from .integer_repair_support import IDENT, view
from .local_flow import analyze
from .pattern_repairs import close

FAMILY = 'split_multiple_rejoin'
BASE_FAMILY = 'base_set_every_arm'
BOTH_FAMILY = 'split_multiple_rejoin_base_set'
FAMILIES = (FAMILY, BASE_FAMILY, BOTH_FAMILY)

_INTEGER = r'(?:unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int)|[su](?:8|16|32)|char|short|int|long)'
_DECL = re.compile(rf'(?m)^[ \t]*(?P<type>{_INTEGER})\s+(?P<name>{IDENT})\s*;[ \t]*\n')
_POINTER = re.compile(rf'(?m)^[ \t]*(?P<type>{IDENT}(?:\s+{IDENT})?)\s*(?:\*\s*)+(?P<name>{IDENT})\s*;[ \t]*\n')
_TOKEN = re.compile(rf'\s*(0[xX][0-9a-fA-F]+|[0-9]+|<<|{IDENT}|[()+*])')
_CHANGE = r'(?:\b{0}\s*(?:=(?!=)|\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{0}\b)'


def _evaluate(text, values):
    """`text` as (multiple, constant) of the value `values` measures, or None for anything that is not such a sum."""
    tokens, position = [], 0
    while position < len(text.rstrip()):
        token = _TOKEN.match(text, position)
        if not token:
            return None
        tokens.append(token[1])
        position = token.end()
    index = 0

    def take(*wanted):
        nonlocal index
        if index < len(tokens) and tokens[index] in wanted:
            index += 1
            return tokens[index - 1]
        return None

    def factor():
        nonlocal index
        if take('('):
            value = shift()
            return value if take(')') else None
        if index >= len(tokens):
            return None
        token = tokens[index]
        index += 1
        if token[0].isdigit():
            try:
                return (0, int(token, 0))
            except ValueError:
                return None
        return (values[token], 0) if token in values else None

    def term():
        value = factor()
        while value is not None and take('*'):
            other = factor()
            if other is None or (value[0] and other[0]):
                return None
            value = (value[0] * other[1] + other[0] * value[1], value[1] * other[1])
        return value

    def total():
        value = term()
        while value is not None and take('+'):
            other = term()
            if other is None:
                return None
            value = (value[0] + other[0], value[1] + other[1])
        return value

    def shift():
        value = total()
        while value is not None and take('<<'):
            other = total()
            if other is None or other[0] or not 0 <= other[1] < 32:
                return None
            value = (value[0] << other[1], value[1] << other[1])
        return value

    result = shift()
    return result if index == len(tokens) else None


def _assignments(part, name):
    """The plain `name = expr;` statements, or None when the local is changed any other way (or its address taken)."""
    body = part.clean[part.opening:part.end]
    if re.search(rf'(?<!&)&(?!&)\s*(?:\(\s*)*{name}\b', body):
        return None
    plain = list(re.finditer(rf'(?m)(?<=[;{{}}:\n])[ \t]*{name}\s*=(?!=)\s*(?P<value>[^;{{}}]*?)\s*;', body))
    if not plain or len(plain) != len(re.findall(_CHANGE.format(name), body)):
        return None
    return [(part.opening + hit.start(), part.opening + hit.end(), hit['value']) for hit in plain]


def _reached(flow, makes, breaks):
    """For each block: on every path into it, is the property made (by `makes`) and not broken since?"""
    order, predecessors = flow.reachability()
    inside = {index: index != flow.entry for index in order}
    outside = {index: True for index in order}
    changed = True
    while changed:
        changed = False
        for index in order:
            entering = index != flow.entry and all(outside[p] for p in predecessors[index])
            text = flow.part.clean[flow.nodes[index].start:flow.nodes[index].end]
            leaving = True if makes(text) else False if breaks(text) else entering
            if (entering, leaving) != (inside[index], outside[index]):
                inside[index], outside[index] = entering, leaving
                changed = True
    return inside


def _reads(flow, name):
    """The blocks that read `name` (its own plain assignment's left side is not a read)."""
    for index in flow.reachability()[0]:
        node = flow.nodes[index]
        text = flow.part.clean[node.start:node.end]
        if re.match(rf'\s*{IDENT}[\s\S]*?\b{name}\s*;\s*$', text) and not re.search(r'[=(]', text):
            continue  # (the declaration)
        text = re.sub(rf'^\s*{name}\s*=(?!=)', '', text)
        if re.search(rf'(?<![\w.])(?<!->){name}\b', text):
            yield index


def _multiples(source, name, part):
    """(value, {local: multiple}) for the integer locals that only ever hold one multiple of `value`."""
    signature = part.clean[:part.opening]
    signature = signature[signature.rfind('(') + 1:]
    declared = {m['name']: m for m in _DECL.finditer(part.clean, part.opening, part.end)}
    parameters = set(re.findall(rf'{_INTEGER}\s+({IDENT})', signature))
    stated = {n: _assignments(part, n) for n in declared}
    stated = {n: rows for n, rows in stated.items() if rows}
    best = None
    for value in sorted(set(declared) | parameters):
        if re.search(rf'(?<!&)&(?!&)\s*{value}\b', part.clean[part.opening:part.end]):
            continue
        known = {value: 1}
        while True:
            found = {}
            for local, rows in stated.items():
                if local in known:
                    continue
                results = {_evaluate(text, known) for _, _, text in rows}
                if len(results) == 1 and None not in results:
                    multiple, constant = next(iter(results))
                    if not constant and multiple > 1:
                        found[local] = multiple
            if not found:
                break
            known.update(found)
        del known[value]
        if known and (best is None or len(known) > len(best[1])):
            best = (value, known)
    if not best:
        return None
    value, known = best
    flow = analyze(source, name, declarations=[declared[n] for n in known], allow_unrelated_volatile=True)
    if not flow:
        return None
    fresh = {}
    for local, multiple in known.items():
        inside = _reached(flow,
                          lambda text, local=local: re.match(rf'\s*{local}\s*=(?!=)', text),
                          lambda text: re.search(_CHANGE.format(value), text))
        if all(inside[index] for index in _reads(flow, local)):
            fresh[local] = multiple
    return (value, fresh, declared, stated) if fresh else None


def _number(value):
    return str(value) if value < 16 else f'0x{value:X}'


def _fold(text, value, markers):
    """Every outermost parenthesised sum that holds a marker, written as `(value * K)`; leftover markers too."""
    position = 0
    known = dict(markers, **{value: 1})
    while True:
        opening = text.find('(', position)
        if opening < 0:
            break
        end = close(text, opening)
        if end is None:
            break
        group = text[opening:end]
        if any(re.search(rf'\b{marker}\b', group) for marker in markers):
            result = _evaluate(group, known)
            if result and not result[1] and result[0] > 1:
                folded = f'({value} * {_number(result[0])})'
                text = text[:opening] + folded + text[end:]
                position = opening + len(folded)
                continue
        position = opening + 1
    for marker, multiple in markers.items():
        text = re.sub(rf'\b{marker}\b', f'({value} * {_number(multiple)})', text)
    return text


def rejoin(source, name):
    """`source` with the staged multiples folded back, or None."""
    part = view(source, name)
    if not part or '__rejoin' in source:
        return None
    found = _multiples(source, name, part)
    if not found:
        return None
    value, fresh, declared, stated = found
    edits, markers = [], {}
    for number, (local, multiple) in enumerate(sorted(fresh.items())):
        marker = f'__rejoin{number}'
        markers[marker] = multiple
        edits.append((declared[local].start(), declared[local].end(), ''))
        removed = []
        for start, end, _ in stated[local]:
            line = source.rfind('\n', 0, start + 1) + 1
            if not source[line:start].strip() and source[end:end + 1] == '\n':
                start, end = line, end + 1
            elif source[start:start + 1] == '\n':
                start += 1
            # (a label needs a statement after it)
            keep = ';' if source[:start].rstrip().endswith(':') else ''
            removed.append((start, end))
            edits.append((start, end, keep + '\n' if keep else ''))
        for hit in re.finditer(rf'(?<![\w.])(?<!->){local}\b', part.clean[part.opening:part.end]):
            at = part.opening + hit.start()
            if declared[local].start() <= at < declared[local].end() or any(a <= at < b for a, b in removed):
                continue
            edits.append((at, at + len(local), marker))
    # a read inside another local's removed assignment goes with that statement
    spans = [(a, b) for a, b, text in edits if not text.startswith('__rejoin')]
    edits = [(a, b, text) for a, b, text in edits
             if not text.startswith('__rejoin') or not any(x <= a < y for x, y in spans)]
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    return _fold(source, value, markers)


def _blocks(clean, opening, position):
    """The opening braces around `position`, outermost first."""
    stack = []
    for hit in re.finditer(r'[{}]', clean[opening:position]):
        if hit[0] == '{':
            stack.append(opening + hit.start())
        elif stack:
            stack.pop()
    return stack


def _set_bases(source, name, before_statement):
    """Assign each symbol-address local where a read of it is not reached by an assignment, or None."""
    changed = False
    for _ in range(8):
        part = view(source, name)
        if not part:
            return None
        placed = False
        for decl in _POINTER.finditer(part.clean, part.opening, part.end):
            local = decl['name']
            rows = _assignments(part, local)
            if not rows or len({text.replace(' ', '') for _, _, text in rows}) != 1:
                continue
            address = rows[0][2]
            symbol = re.fullmatch(rf'&?\s*({IDENT})', address)
            if not symbol or re.search(rf'[\w)\]][\s*]+{symbol[1]}\s*[;=,)\[]', part.clean[part.opening:part.end]):
                continue  # (not a plain global's address: a local or a computed value)
            flow = analyze(source, name, declarations=[decl], allow_unrelated_volatile=True)
            if not flow:
                continue
            inside = _reached(flow, lambda text, local=local: re.match(rf'\s*{local}\s*=(?!=)', text),
                              lambda text: False)
            missing = sorted(flow.nodes[i].start for i in _reads(flow, local) if not inside[i])
            if not missing:
                continue
            statement = f'{local} = {address};'
            if before_statement:
                line = source.rfind('\n', 0, missing[0]) + 1
                text = part.clean[line:missing[0]]
                if text.strip().startswith(('}', 'else', 'case', 'default', 'while', 'for')):
                    return None
                indent = text[:len(text) - len(text.lstrip())]
                source = source[:line] + f'{indent}{statement}\n' + source[line:]
            else:
                at = _blocks(part.clean, part.opening, missing[0])[-1] + 1
                declarations = re.match(rf'(?:\s*(?:{IDENT}\s+)+\**\s*{IDENT}\s*(?:\[[^]]*\])?;)*', part.clean[at:])
                if declarations and not re.match(r'\s*(?:return|goto)\b', declarations[0]):
                    at += declarations.end()
                line = part.clean[at:].split('\n', 2)
                following = line[1] if len(line) > 1 else ''
                indent = following[:len(following) - len(following.lstrip())] or '    '
                source = source[:at] + f'\n{indent}{statement}' + source[at:]
            changed = placed = True
            break
        if not placed:
            break
    return source if changed else None


def variants(source, name):
    result = []
    rejoined = rejoin(source, name)
    if rejoined:
        for placement in (False, True):
            both = _set_bases(rejoined, name, placement)
            if both:
                result.append((BOTH_FAMILY, both))
        result.append((FAMILY, rejoined))
    for placement in (False, True):
        based = _set_bases(source, name, placement)
        if based:
            result.append((BASE_FAMILY, based))
    unique = []
    for child in result:
        if child[1] != source and child[1] not in [text for _, text in unique]:
            unique.append(child)
    return unique


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
