"""A join label m2c left inside one arm's nest, moved out to a shared tail after the arms that jump to it.

m2c writes the code two switch arms share where it first met it. An `if`/`else` in the first arm ends up holding the
labels the second arm jumps into:

    case 1:
        if (a == 0) {
            if (b != 0) {
                v = first();
block_1:
                if (v == 0) { goto block_2; }
            } else {
                r = second();
block_2:
                third(r);
            }
        }
        break;
    case 2:
        ... goto block_2; ... goto block_1; ...

GCC 2.7.2 lays blocks out in source order, so that nest decides where the shared call sits in the object code. A
game whose shared tail came after the second arm's own tests (the first arm's `else` branched forward to it) was
written with the tail there. The same behaviour, in that layout: each nested label's tail becomes a `goto` at its old
place, and the labelled tails follow the last arm that jumps to them, closed by a `break`:

    case 1:
        if (a == 0) {
            if (b != 0) { v = first(); goto block_1; }
            r = second();
            goto block_2;
        }
        break;
    case 2:
        ...
        break;
block_1:
        if (v != 0) { break; }       /* a tail that only jumps to the next label falls into it */
block_2:
        third(r);
        break;

Only labels that another arm jumps to are moved, and only when what follows the nest inside its arm is closing braces,
`else` branches and the arm's `break` (so the `break` at the end of the moved tail is the old fall-out). Two variants:
the tails after the arm that holds them, and after the last arm that jumps to them. The judge decides.
"""
import re
import textwrap

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'nested_join_hoist'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
_LABEL = re.compile(r'(?m)^[ \t]*(?P<name>' + IDENT + r')[ \t]*:(?!:)')
_CASE = re.compile(r'(?m)^[ \t]*(?:case\b[^:;{}]*|default)\s*:(?!:)')
_NOT_LABELS = {'case', 'default', 'public', 'private', 'protected'}


def _block_end(clean, open_at):
    """Index of the `}` that closes the `{` at `open_at`, or None."""
    end = close(clean, open_at, '{', '}')
    return end - 1 if end else None


def _enclosing_block(clean, at, floor):
    """(open, close) of the innermost `{...}` around `at`, above `floor`."""
    depth = 0
    for pos in range(at - 1, floor - 1, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                end = _block_end(clean, pos)
                return (pos, end) if end and end > at else None
            depth -= 1
    return None


def _is_switch_body(clean, open_at, floor):
    """True when the `{` at `open_at` opens the body of `switch (...)`."""
    before = clean[floor:open_at].rstrip()
    if not before.endswith(')'):
        return False
    depth = 0
    for pos in range(len(before) - 1, -1, -1):
        depth += (before[pos] == ')') - (before[pos] == '(')
        if depth == 0:
            return re.search(r'\bswitch\s*$', before[:pos]) is not None
    return False


def _switch_of(clean, at, floor):
    """The innermost `switch` body (open, close) around `at`."""
    pos = at
    while True:
        block = _enclosing_block(clean, pos, floor)
        if not block:
            return None
        if _is_switch_body(clean, block[0], floor):
            return block
        pos = block[0]


def _arms(clean, switch):
    """[(start, end)] of each arm of the switch body: from a `case`/`default` label to the next at the same depth."""
    inner = clean[switch[0] + 1:switch[1]]
    starts = []
    for hit in _CASE.finditer(inner):
        at = switch[0] + 1 + hit.start()
        depth = clean.count('{', switch[0] + 1, at) - clean.count('}', switch[0] + 1, at)
        if depth == 0:
            starts.append(at)
    ends = starts[1:] + [switch[1]]
    return list(zip(starts, ends))


def _falls_out(clean, at, arm_end):
    """True when, after the `}` just before `at`, control only leaves the arm: closing braces, `else` branches and
    the arm's `break`."""
    pos = at
    while pos < arm_end:
        rest = clean[pos:arm_end]
        stripped = rest.lstrip()
        pos += len(rest) - len(stripped)
        if not stripped:
            return False
        if stripped.startswith('}'):
            pos += 1
        elif re.match(r'else\b\s*\{', stripped):
            start = pos + stripped.index('{')
            end = _block_end(clean, start)
            if end is None:
                return False
            pos = end + 1
        else:
            return re.match(r'break\s*;\s*$', stripped) is not None
    return False


def _tail_text(source, clean, label_end, block_end):
    return source[label_end:block_end].strip('\n')


def _fuse(tail, label_after, indent):
    """`if (c) { goto next; }` alone, written before `next:` itself, becomes `if (!(c)) { break; }`."""
    hit = re.fullmatch(r'\s*if\s*\((.+)\)\s*\{\s*goto\s+(' + IDENT + r')\s*;\s*\}\s*', tail, re.S)
    if not hit or hit[2] != label_after:
        return None
    condition = negate(hit[1].strip()) or f'!({hit[1].strip()})'
    return f'{indent}if ({condition}) {{\n{indent}    break;\n{indent}}}\n'


def _reindent(tail, indent):
    lines = [line for line in textwrap.dedent(tail.strip('\n')).splitlines() if line.strip()]
    return textwrap.indent('\n'.join(lines), indent) + '\n'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0])
    if opening < 0:
        return []
    end = _block_end(clean, opening)
    if end is None:
        return []
    labels = {}
    for hit in _LABEL.finditer(clean, opening, end):
        if hit['name'] not in _NOT_LABELS and re.search(rf'\bgoto\s+{hit["name"]}\s*;', clean[opening:end]):
            labels[hit['name']] = hit
    found = []
    for label, hit in labels.items():
        switch = _switch_of(clean, hit.start(), opening)
        block = _enclosing_block(clean, hit.start(), opening)
        if not switch or not block or block == switch:
            continue
        arms = [arm for arm in _arms(clean, switch) if arm[0] <= hit.start() < arm[1]]
        if not arms:
            continue
        arm = arms[0]
        if not (arm[0] < block[0] and block[1] < arm[1]) or not _falls_out(clean, block[1] + 1, arm[1]):
            continue
        outside = [g.start() for g in re.finditer(rf'\bgoto\s+{label}\s*;', clean[switch[0]:switch[1]])]
        outside = [switch[0] + at for at in outside]
        if not any(not arm[0] <= at < arm[1] for at in outside):
            continue
        found.append(dict(label=label, hit=hit, block=block, arm=arm, switch=switch, gotos=outside))
    if not found:
        return []
    # moved together when they sit in the same arm; one group per arm
    result = []
    arms = []
    for item in found:
        if item['arm'] not in arms:
            arms.append(item['arm'])
    for arm in arms:
        group = [item for item in found if item['arm'] == arm]
        group.sort(key=lambda item: item['hit'].start())
        names = [item['label'] for item in group]
        switch = group[0]['switch']
        every = _arms(clean, switch)
        referencing = [a for a in every if any(a[0] <= g < a[1] for item in group for g in item['gotos'])]
        for where in (arm, max(referencing)):
            text = _hoist(source, clean, group, names, where)
            if text and text not in result:
                result.append(text)
    return [(FAMILY, text) for text in result[:4]]


def _hoist(source, clean, group, names, where):
    # the arm we append to must end by leaving, so the tails are reached only by `goto`
    arm_text = clean[where[0]:where[1]].rstrip()
    if not re.search(r'(?:\bbreak|\breturn\b[^;]*|\bgoto\s+\w+)\s*;\s*(?:\})?$', arm_text) and where[1] != group[0]['switch'][1]:
        return None
    edits = []
    tails = []
    for index, item in enumerate(group):
        hit, block = item['hit'], item['block']
        label_end = hit.end()
        tail = source[label_end:block[1]]
        if not tail.strip():
            return None
        after = names[index + 1] if index + 1 < len(names) else None
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, block[1]) + 1:]).group()
        arm_indent = re.match(r'[ \t]*', source[where[0]:]).group() + '    '
        fused = _fuse(tail, after, arm_indent) if after else None
        tails.append((item['label'], fused if fused is not None else _reindent(tail, arm_indent), fused is not None))
        edits.append((hit.start(), block[1], f'{indent}    goto {item["label"]};\n{indent}'))
    arm_break = re.match(r'[ \t]*', source[where[0]:]).group() + '    break;\n'
    chain = ''
    for label, text, fused in tails:
        chain += f'{label}:\n{text}'
        if not fused:
            chain += arm_break

    out = source
    # later edits first, so earlier offsets stay valid; the hoisted tails go in at the end of `where`
    for a, b, text in sorted(edits + [(where[1], where[1], chain)], key=lambda e: e[0], reverse=True):
        out = out[:a] + text + out[b:]
    return out
