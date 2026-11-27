"""A loop's (or void function's) `if (v == K) {... continue;}` guards and last `if (v != K2) continue;`, as a `switch`.

    for (;;) {                                  for (;;) {
    loop_2:                                         recv(&queue, &msg, 1);
        recv(&queue, &msg, 1);                      kind = msg->kind;
        kind = msg->kind;                           switch (kind) {
        if (kind == 1) {                            case 1:
            if (start(pad) == 0) {...}                  if (start(pad) == 0) {...}
            continue;                        ->         break;
        }                                           case 2:
        slot = channel * 0x68;                          slot = channel * 0x68;
        do { if (kind != 2) { goto loop_2; } } while (0);
        if (stop(pad + slot) != 0) {                    if (stop(pad + slot) != 0) {
            continue;                                       continue;
        }                                               }
        state[channel] = 0;                             state[channel] = 0;
        continue;                                       break;
    break;                                          }
    }                                           }

m2c reads a small `switch` that ends a loop body this way. Written as `if`s, GCC tests the second value only after the
first arm's code; a `switch` is expanded as one compare chain (`expand_end_case`) ahead of both arms, so the branches,
the delay slots and the saved registers holding the compared constants differ. A 56-instruction N64 message thread
(SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mfp64`) went 1126 -> 0 from its machine draft with this rewrite alone.

`variants` reads every `for (;;)` / `while (1)` body, and the body of a `void` function. In it: one or more
`if (V == K) { ...; EXIT }` guards (no `else`), optionally followed by `if (V != K2) { EXIT }` (also `goto` a label at the
head of the loop body, and inside braces or `do { } while (0);`), then the rest of the region. `EXIT` is `continue;` in a
loop and `return;` in a function. With the `!=` guard the rest is `case K2:`; without it (two guards or more) the rest
is `default:`. Assignments of plain locals between the guards move into the last arm, only when nothing else reads them.
A region whose arms `break` out of the loop, or hold labels, is left alone.
"""
import re

from .arm_block_support import statements
from .c_scan import close, header_before
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'exit_dispatch_switch'
FAMILIES = (FAMILY,)
LIMIT = 4
EQUAL = re.compile(rf'if\s*\(\s*({IDENT})\s*==\s*({NUMBER})\s*\)\s*\{{')
UNEQUAL = re.compile(rf'if\s*\(\s*({IDENT})\s*!=\s*({NUMBER})\s*\)\s*')
LABEL = re.compile(rf'(?!case\b|default\b)({IDENT})\s*:(?!:)\s*')
FENCE = re.compile(r'(?:do\s*)?\{(.*)\}(?:\s*while\s*\(\s*0\s*\)\s*;)?', re.S)
STAGE = re.compile(rf'({IDENT})\s*=(?!=)([^=;{{}}]*);')
CASTS = re.compile(rf'(?<![\w\])\s])\s*\(\s*(?:(?:unsigned|signed|struct)\s+)?{IDENT}[\s*]*\)')


def _loops(part):
    """The (opening, closing, exit statement) of every endless loop body, and of a void function's body."""
    clean = part.clean
    found = []
    for hit in re.finditer(r'\{', clean[part.opening + 1:part.end]):
        opening = part.opening + 1 + hit.start()
        if re.fullmatch(r'(?:for\s*\(\s*;\s*;\s*\)|while\s*\(\s*1\s*\))', header_before(clean, opening)):
            closing = close(clean, opening)
            if closing > 0:
                found.append((opening, closing, 'continue'))
    head = clean[:part.opening]
    head = head[max(head.rfind(';'), head.rfind('}')) + 1:]
    if re.search(r'\bvoid\s+' + IDENT + r'\s*\(', head):
        found.append((part.opening, close(clean, part.opening), 'return'))
    return found


def _items(clean, opening, closing):
    """The region's top-level statements as (start, end, labels), `start` past the labels."""
    items = []
    for start, end in statements(clean, opening + 1, closing):
        labels = []
        while True:
            hit = LABEL.match(clean, start, end)
            if not hit:
                break
            labels.append((hit[1], start, hit.end()))
            start = hit.end()
        items.append((start, end, labels))
    return items


def _leaves(text, exit_word, heads):
    """Whether `text` is just the exit: `continue;` / `return;`, or a `goto` the loop's head, fenced or not."""
    text = text.strip()
    while True:
        hit = FENCE.fullmatch(text)
        if not hit:
            break
        text = hit[1].strip()
    if re.fullmatch(exit_word + r'\s*;', text):
        return True
    jump = re.fullmatch(r'goto\s+(' + IDENT + r')\s*;', text)
    return bool(jump) and jump[1] in heads


def _unfenced_unequal(text, exit_word, heads):
    """(name, constant) when the statement is `if (V != K) EXIT`, maybe inside braces or `do { } while (0);`."""
    text = text.strip()
    while True:
        hit = UNEQUAL.match(text)
        if hit:
            return (hit[1], hit[2]) if _leaves(text[hit.end():], exit_word, heads) else None
        fence = FENCE.fullmatch(text)
        if not fence:
            return None
        text = fence[1].strip()


def _own_break(text):
    """Whether `text` has a `break` that is not inside a loop or switch of its own."""
    stack, boundary, parens = [], 0, 0
    for at, char in enumerate(text):
        if char in '()':
            parens += 1 if char == '(' else -1
        elif parens:
            continue
        elif char == '{':
            header = text[boundary:at].strip()
            stack.append(bool(re.search(r'(?:\b(?:for|while|switch)\s*\(.*\)|\bdo)$', header, re.S)))
            boundary = at + 1
        elif char == '}':
            if stack:
                stack.pop()
            boundary = at + 1
        elif char == ';':
            boundary = at + 1
        elif not any(stack) and re.match(r'break\b', text[at:]) and (at == 0 or not text[at - 1].isalnum() and text[at - 1] != '_'):
            return True
    return False


def _stage(part, text, start):
    """The local a plain assignment sets (no call, no store through memory, no declaration elsewhere), or None."""
    hit = STAGE.fullmatch(text.strip())
    if not hit:
        return None
    value = CASTS.sub(' ', '=' + hit[2])
    if re.search(r'\+\+|--|' + IDENT + r'\s*\(|\)\s*\(', value):
        return None
    declared = re.search(rf'[{{;]\s*(?:(?:unsigned|signed)\s+)?(?!return\b){IDENT}[\s*]+{hit[1]}\s*;',
                         part.clean[part.opening:start])
    return hit[1] if declared else None


def _only_in(part, local, spans):
    """Whether every use of `local` besides its declaration is inside the spans."""
    outside = 0
    for hit in re.finditer(rf'\b{local}\b', part.clean[part.opening:part.end]):
        at = part.opening + hit.start()
        if not any(lo <= at < hi for lo, hi in spans):
            outside += 1
    return outside == 1


def _body(source, lo, hi, indent):
    lines = [line.rstrip() for line in source[lo:hi].split('\n')]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    rest = [line for line in lines[1:] if line.strip()]
    width = min((len(line) - len(line.lstrip()) for line in rest), default=0)
    if lines and rest:
        first = len(lines[0]) - len(lines[0].lstrip())
        width = min(width, first) if first else width
    return [indent + (line[width:] if line[:width].isspace() else line.lstrip()) if line.strip() else '' for line in lines]


def _region(part, opening, closing, exit_word):
    clean, source = part.clean, part.source
    items = _items(clean, opening, closing)
    heads = {label for label, _, _ in items[0][2]} if items and exit_word == 'continue' else set()
    # the unreachable `break;` m2c leaves after the loop's last `continue;`, and the trailing exit itself
    end = len(items)

    def text(index):
        return clean[items[index][0]:items[index][1]]

    exit_text = re.compile(exit_word + r'\s*;')
    if exit_word == 'continue' and end > 1 and re.fullmatch(r'break\s*;', text(end - 1)) and not items[end - 1][2] \
            and exit_text.fullmatch(text(end - 2)):
        end -= 1
    first = next((i for i in range(end) if EQUAL.match(text(i))), None)
    if first is None:
        return None
    name = EQUAL.match(text(first))[1]
    arms, constants, stages, last, at = [], [], [], None, first
    while at < end:
        start, stop, labels = items[at]
        if labels and at != first:
            return None
        hit = EQUAL.match(clean, start, stop)
        if hit and hit[1] == name:
            brace = hit.end() - 1
            shut = close(clean, brace)
            if shut != stop - 1:
                return None
            inner = clean[brace + 1:shut].rstrip()
            tail = re.search(r'(?:^|[;{}])\s*(' + exit_word + r'\s*;)$', inner)
            if not tail or hit[2] in constants:
                break
            constants.append(hit[2])
            arms.append((brace + 1, brace + 1 + tail.start(1)))
            at += 1
            continue
        unequal = _unfenced_unequal(clean[start:stop], exit_word, heads)
        if unequal and unequal[0] == name:
            if unequal[1] in constants:
                return None
            last = (unequal[1], at)
            break
        local = _stage(part, clean[start:stop], opening)
        if local is None or local == name:
            break
        stages.append((local, start, stop))
        at += 1
    if not arms:
        return None
    if last:
        constants.append(last[0])
        rest_from = last[1] + 1
        moved = stages
    else:
        if len(arms) < 2:
            return None
        rest_from = at
        moved = []
        if stages:  # no `!=` guard: stages stay with the `default:` they run into
            rest_from = at - len(stages)
    if any(items[i][2] for i in range(rest_from, end)):
        return None
    rest_end = end
    if rest_end > rest_from and exit_text.fullmatch(text(rest_end - 1)):
        rest_end -= 1
    rest = (items[rest_from][0], items[rest_end - 1][1]) if rest_end > rest_from else None
    if last and not rest:
        return None
    for lo, hi in arms + ([rest] if rest else []):
        if _own_break(clean[lo:hi]) or re.search(rf'(?:^|[;{{}}])\s*{LABEL.pattern}', clean[lo:hi]):
            return None
    for local, _, _ in moved:
        if not _only_in(part, local, [rest] + [(lo, hi) for _, lo, hi in moved if _ == local]):
            return None
    begin = items[first][0]
    line = source[source.rfind('\n', 0, begin) + 1:begin]
    indent = re.match(r'[ \t]*', line)[0]
    deeper = indent + '    '
    out = [f'switch ({name}) {{']
    for index, (lo, hi) in enumerate(arms):
        out.append(f'{indent}case {constants[index]}:')
        out += _body(source, lo, hi, deeper)
        out.append(f'{deeper}break;')
    if rest or moved:
        out.append(f'{indent}case {constants[-1]}:' if last else f'{indent}default:')
        out += [deeper + source[lo:hi] for _, lo, hi in moved]
        if rest:
            out += _body(source, rest[0], rest[1], deeper)
        out.append(f'{deeper}break;')
    out.append(f'{indent}}}')
    stop = items[-1][1]
    changes = [(begin, stop, '\n'.join(out))]
    # a loop-head label only the removed `goto` named is dropped with it
    for label, lo, hi in items[0][2]:
        uses = [part.opening + m.start() for m in re.finditer(rf'\bgoto\s+{label}\b', clean[part.opening:part.end])]
        if uses and all(begin <= use < stop for use in uses) \
                and not re.search(rf'\bgoto\s+{label}\b', '\n'.join(out)):
            hi = re.compile(label + r'[ \t]*:[ \t]*\n?').match(source, lo).end()
            changes.append((lo, hi, ''))
    return edit(source, sorted(changes))


def variants(source, name):
    part = view(source, name)
    if not part or 'if' not in part.body:
        return []
    results = []
    for opening, closing, exit_word in _loops(part):
        text = _region(part, opening, closing, exit_word)
        if text and text != source and (FAMILY, text) not in results:
            results.append((FAMILY, text))
    return results[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}
