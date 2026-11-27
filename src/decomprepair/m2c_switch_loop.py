"""m2c's label-and-`goto` loop around a `switch`, with a tail its arms share, written as `for (;;) { switch; TAIL }`.

m2c cannot say that a `switch` sits in a loop, so a text-drawing walk comes out as

    loop_1:
        c = *p;
        switch (c) {
        case 0:
            break;                      /* leaves the loop */
        default:
            ...
            v = glyph + *x;
            goto block_9;
        case 32:
            v = *x + 14.0f;
    block_9:
            *x = v;
            p += 1;
            goto loop_1;
        }
        return total;

The tail inside the last arm is what every arm that stays in the loop runs, so it belongs after the `switch` inside a
loop: the arms' `goto block_9` (and the last arm's fall into it) become `break`, the old `break`s (which left the
`switch` and the loop with it) become `goto loop_exit;`, and the label sits before the code after the `switch`:

    for (;;) {
        c = *p;
        switch (c) {
        case 0:
            goto loop_exit;
        default:
            ...
            break;
        case 32:
            v = *x + 14.0f;
            break;
        }
        *x = v;
        p += 1;
    }
    loop_exit:
    return total;

On an N64 text-drawing loop (SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mfp32`) the m2c form was 2433 and this one 15
(`switch_arm_accumulate` then gave 0).

The same program, or nothing: the loop label has the one `goto` that ends the `switch`; the tail's label is reached
only by `goto`s standing directly in the arms; the `switch` has a `default` (an unmatched value must not run the tail);
the statements before the `switch` and the tail hold no label, jump, `case` or declaration; no `continue`, and no
loop or nested `switch` in the arms (its `break` would be rewritten)."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'm2c_switch_loop'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
EXIT = '__repair_loop_exit'
_JUMPS = re.compile(r'\b(?:goto|break|continue|return|case|default|for|while|do|switch|if|else)\b|[{}]')
_LABEL = re.compile(rf'(?m)^[ \t]*(?!default\b|case\b)({IDENT})[ \t]*:(?!:)')
_DECLARATION = re.compile(rf'(?:^|;)\s*(?!return\b){IDENT}(?:\s*\*+\s*|\s+){IDENT}\s*(?:[=;\[]|$)')


def _rewrite(source, clean, opening, end, loop):
    name = loop[1]
    if len(re.findall(rf'\bgoto\s+{name}\s*;', clean)) != 1:
        return None
    head = re.compile(r'\bswitch\s*\(').search(clean, loop.end(), end)
    if not head or _JUMPS.search(clean[loop.end():head.start()]) or _LABEL.search(clean, loop.end(), head.start()):
        return None
    if _DECLARATION.search(clean[loop.end():head.start()]):
        return None
    paren = close(clean, head.end() - 1, '(', ')')
    brace = clean.find('{', paren) if paren else -1
    stop = close(clean, brace, '{', '}') if brace >= 0 and not clean[paren:brace].strip() else None
    if not stop:
        return None
    stop -= 1  # the switch's `}`
    back = re.search(rf'\bgoto\s+{name}\s*;\s*$', clean[brace + 1:stop])
    if not back:
        return None
    back_at = brace + 1 + back.start()
    labels = list(_LABEL.finditer(clean, brace + 1, back_at))
    if len(labels) != 1:
        return None
    label = labels[0]
    tail = clean[label.end():back_at]
    if _JUMPS.search(tail) or _DECLARATION.search(tail) or not tail.strip():
        return None
    arms = clean[brace + 1:label.start()]
    if (re.search(r'\b(?:continue|for|while|do|switch)\b|\b__repair_loop_exit\b', arms)
            or not re.search(r'\bdefault\s*:', arms)):
        return None
    target = label[1]
    jumps = [m for m in re.finditer(rf'\bgoto\s+{target}\s*;', clean)]
    if any(not (brace < m.start() < label.start()) for m in jumps):
        return None
    edits = []
    for hit in re.finditer(rf'\bbreak\s*;|\bgoto\s+{target}\s*;', arms):
        edits.append((brace + 1 + hit.start(), brace + 1 + hit.end(),
                      f'goto {EXIT};' if hit[0].startswith('break') else 'break;'))
    line = clean.rfind('\n', 0, head.start()) + 1
    indent = re.match(r'[ \t]*', source[line:])[0]
    inner = source[loop.end():head.start()].strip()
    body = source[head.start():label.start()]
    for first, last, new in sorted(edits, reverse=True):
        body = body[:first - head.start()] + new + body[last - head.start():]
    body = body.rstrip()
    if not re.search(r'(?:\bbreak\s*;|\breturn\b[^;{}]*;|\bgoto\s+\w+\s*;)$', body):
        body += f'\n{indent}    break;'  # the last arm fell into the tail
    shared = '\n'.join(indent + '    ' + part.strip() for part in source[label.end():back_at].split('\n') if part.strip())
    after = source[stop + 1:]
    text = ('for (;;) {\n'
            + (''.join(f'{indent}    {part.strip()}\n' for part in inner.split('\n') if part.strip()))
            + f'{indent}    ' + body + f'\n{indent}    }}\n'
            + shared + f'\n{indent}}}')
    if re.search(rf'\bgoto\s+{EXIT}\s*;', text):
        text += f'\n{EXIT}:'
        if re.match(r'\s*\}', after):
            text += ' ;'
    return source[:loop.start()] + indent + text + after


def variants(source, name):
    """[(family, source)] with the first such loop written as `for (;;)`, or []."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0 or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|(?m:^[ \t]*#)', clean[opening:end]):
        return []
    for loop in _LABEL.finditer(clean, opening, end):
        child = _rewrite(source, clean, opening, end, loop)
        if child:
            return [(FAMILY, child)]
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}
