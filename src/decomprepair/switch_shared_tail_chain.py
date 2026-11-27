"""A switch whose arms share a tail kept inside one of them, written as the `else if` chain it came from.

Measured on a 52-instruction N64 object update (SN gcc 2.8.1, `-G0 -mips3 -O2 -mgas`). The target compares a field with
three values in turn, adds a step per value and then runs a tail unless the field holds one of them; a value that
matches nothing goes straight to the tail. m2c wrote that as a switch whose first arm holds the tail behind a label,
with `default:` jumping into the middle of the tail's own test:

    switch (v) {                                    if (v == K1) {
    case K1:                                            S1 P
        S1                                          } else if (v == K2) {
    block:                                              S2 P
        P                                           } else if (v == K3) {
        if (E != K3) {              ->                  S3 P
    default:                                        }
            BODY                                    if (E != K3) {
        }                                               BODY
        break;                                      }
    case K2: S2 goto block;
    case K3: S3 goto block;
    }

The two mean the same: a value no case names reaches BODY directly, and the chain's test `E != K3` is true for it
(K3 is a case value and nothing ran that could change E), so it reaches BODY too. gcc builds a compare tree for the
switch and the plain chain of the target for the `if`s. From the saved best the rewrite took 2425 to 210; the call's
fourth argument and reading the field in each test finished it (`target_call_arity`, `field_copy_reread`).

Candidate rewrites; the exact judge decides each.
"""
import re
import textwrap

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_shared_tail_chain'
FAMILIES = (FAMILY,)
LIMIT = 4

_SWITCH = re.compile(r'(?<![\w])switch\s*\(')
_CASE = re.compile(r'(?<![\w])(?:case\s+(?P<value>[^:;{}?]+?)|(?P<default>default))\s*:(?!:)')
_LABEL = re.compile(r'(?<![\w?])(?P<label>[A-Za-z_]\w*)\s*:(?!:)')
_NUMBER = re.compile(r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*')


def _number(text):
    text = text.strip()
    if not _NUMBER.fullmatch(text):
        return None
    return int(text.rstrip('uUlL'), 0) if not re.match(r'-?0\d', text) else None


def _squeeze(text):
    """`text` without blanks and the brackets around all of it."""
    text = re.sub(r'\s+', '', text)
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1]
    return text


def _pure(expression):
    """A read that can be done again: no call, assignment, step or volatile."""
    if re.search(r'\+\+|--|(?<![=!<>])=(?!=)|\bvolatile\b', expression):
        return False
    return all(name in ('M2C_FIELD', 'sizeof') for name in re.findall(r'\b([A-Za-z_]\w*)\s*\(', expression))


def _simple(clean):
    """Statements only: no block, label or jump out."""
    return not re.search(r'[{}]|\b(?:break|continue|return|goto|case|default|if|else|for|while|do|switch)\b', clean) \
        and not re.search(r'(?<![\w?])[A-Za-z_]\w*\s*:(?!:)', clean.split('?')[0]) \
        and (not clean.strip() or clean.rstrip().endswith(';'))


def _arms(clean, start, end):
    """[(label start, value or None, body start, body end)] for the labels at the switch block's own depth."""
    marks = [match for match in _CASE.finditer(clean, start, end)
             if clean.count('{', start, match.start()) == clean.count('}', start, match.start())]
    if not marks or clean[start:marks[0].start()].strip():
        return None
    ends = [mark.start() for mark in marks[1:]] + [end]
    return [(mark.start(), mark['value'], mark.end(), stop) for mark, stop in zip(marks, ends)]


def _host(body, clean, start, end):
    """(S1, P, label, condition, BODY, extra labels) of the arm that holds the shared tail."""
    label = _LABEL.search(clean, start, end)
    if not label or label['label'] in ('case', 'default') or not _simple(clean[start:label.start()]):
        return None
    test = re.compile(r'(?<![\w])if\s*\(').search(clean, label.end(), end)
    if not test or not _simple(clean[label.end():test.start()]):
        return None
    condition_end = close(clean, test.end() - 1)
    if condition_end is None:
        return None
    brace = condition_end + len(clean[condition_end:end]) - len(clean[condition_end:end].lstrip())
    if not clean.startswith('{', brace):
        return None
    stop = close(clean, brace, '{', '}')
    if stop is None or not re.fullmatch(r'\s*(?:break\s*;)?\s*', clean[stop:end]):
        return None
    inner = brace + 1
    labels = []
    while True:
        found = _CASE.match(clean, inner + len(clean[inner:stop - 1]) - len(clean[inner:stop - 1].lstrip()))
        if not found:
            break
        labels.append(found['value'])
        inner = found.end()
    if labels.count(None) != 1:
        return None
    rest = clean[inner:stop - 1]
    # a `break` would leave the switch that is about to go, and another case label would need it
    if re.search(r'\b(?:break|case|default)\b', rest):
        return None
    return (body[start:label.start()], body[label.end():test.start()], label['label'],
            body[test.end():condition_end - 1], body[inner:stop - 1], [value for value in labels if value is not None])


def _lines(text, indent):
    """`text`'s statements at `indent`, their nesting kept."""
    kept = '\n'.join(line.rstrip() for line in text.split('\n') if line.strip())
    return textwrap.indent(textwrap.dedent(kept), indent) + '\n' if kept else ''


def _rewrite(body, clean, switch):
    value_end = close(clean, switch.end() - 1)
    if value_end is None:
        return None
    opening = clean.find('{', value_end)
    if opening < 0 or clean[value_end:opening].strip():
        return None
    block_end = close(clean, opening, '{', '}')
    if block_end is None:
        return None
    value = body[switch.end():value_end - 1].strip()
    while value.startswith('(') and close(value, 0) == len(value):
        value = value[1:-1].strip()
    if not _pure(value) and not re.match(r'[A-Za-z_]\w*\s*=(?!=)', value):
        return None
    arms = _arms(clean, opening + 1, block_end - 1)
    if not arms or len(arms) < 2 or any(arm[1] is None for arm in arms):
        return None
    values = [_number(arm[1]) for arm in arms]
    if None in values or len(set(values)) != len(values):
        return None
    hosts = [(index, host) for index, arm in enumerate(arms) if (host := _host(body, clean, arm[2], arm[3]))]
    if len(hosts) != 1:
        return None
    host_index, (first, shared, label, condition, tail, extra) = hosts[0]
    # every use of the label is one of these arms' closing jumps
    if len(re.findall(rf'\bgoto\s+{label}\b', clean)) != len(arms) - 1:
        return None
    statements = []
    for index, (_, _, start, end) in enumerate(arms):
        if index == host_index:
            statements.append(first)
            continue
        jump = re.search(rf'\bgoto\s+{label}\s*;\s*(?:break\s*;\s*)?$', clean[start:end])
        if not jump or not _simple(clean[start:start + jump.start()]):
            return None
        statements.append(body[start:start + jump.start()])
    # nothing falls into the host arm from the arm above: that one ends in its jump (checked above)
    compare = re.fullmatch(r'(?P<left>.+?)!=(?P<right>[^=&|?]+)', _squeeze(condition), re.S)
    if not compare or _number(compare['right']) not in values or any(_number(item) in values for item in extra):
        return None
    start = switch.start()
    assigned = re.fullmatch(r'(?P<name>[A-Za-z_]\w*)\s*=(?!=)(?P<source>.+)', value, re.S)
    named, source = (assigned['name'], assigned['source']) if assigned else (value, None)
    if source is None:
        before = clean[:start].rstrip()
        if before.endswith(';') and re.fullmatch(r'[A-Za-z_]\w*', named):
            from_ = max(before[:-1].rfind(mark) for mark in ';{}') + 1
            last = re.fullmatch(rf'\s*{named}\s*=(?!=)(.+);', body[from_:len(before)], re.S)
            source = last[1] if last else None
    left = _squeeze(compare['left'])
    read_again = [_squeeze(item) for item in (named, source) if item is not None]
    if left not in read_again or not _pure(left):
        return None
    indent = body[body.rfind('\n', 0, start) + 1:start]
    if indent.strip():
        indent = ''
    inside = indent + '    '
    chain = []
    for index, (arm, text) in enumerate(zip(arms, statements)):
        # an assignment in the head stays in the first test
        test = f'({value})' if assigned and index == 0 else named
        chain.append(f'if ({test} == {arm[1].strip()}) {{\n{_lines(text, inside)}{_lines(shared, inside)}{indent}}}')
    after = f'\n{indent}if ({condition.strip()}) {{\n{_lines(tail, inside)}{indent}}}'
    return body[:start] + ' else '.join(chain) + after + body[block_end:]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    body = source[span[0]:span[1]]
    clean = _blank(body)
    found = []
    for switch in _SWITCH.finditer(clean):
        text = _rewrite(body, clean, switch)
        if text is not None:
            found.append((FAMILY, source[:span[0]] + text + source[span[1]:]))
    return found[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
