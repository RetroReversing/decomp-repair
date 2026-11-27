"""m2c's guarded retry loop, written as the `while` the game had.

The compiler tests a `while` once before the loop and again at its end, and m2c writes both tests out:

    if (flags[i] == 0) {                    n = 0;
        n = 1;                              while (flags[i] == 0) {
    loop_4:                                     if (++n == 4) {
        if (n != 4) {                               fallback();
            i = (i + 1) & 3;                        return;
            n += 1;                 ->           }
            if (flags[i] != 0) {                 i = (i + 1) & 3;
                goto block_6;                }
            }
            goto loop_4;
        }
        fallback();
        return;
    }
    block_6:

On a 187-instruction N64 object spawner (`sn-n64-281 -O2 -mips3`) this took a draft 4010 -> 2660. `goto_backward_loop`
and `loop_else_break` keep the guard, the counter's start at 1 and the `goto` out, so no family offered it.

Offered only when the meaning is unchanged: the two tests read the same thing (after dropping `& 0xFF` / `& 0xFFFF`
and ordering the operands of a sum), the tail after the loop returns, the loop label is used once, and the counter is
not mentioned after the guard.

`variants` gives, labelled `guarded_retry_loop`, one child per loop.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'guarded_retry_loop'
FAMILIES = (FAMILY,)
LIMIT = 4
HEAD = re.compile(r'(?m)^(?P<indent>[ \t]*)if \((?P<first>[^\n{}]+?) == 0\) \{\s*(?P<n>[A-Za-z_]\w*) = 1;\s*'
                  r'(?P<loop>\w+):\s*if \((?P=n) != (?P<limit>\w+)\) \{')
BODY = re.compile(r'(?P<steps>.*?)\bif \((?P<second>[^\n{}]+?) != 0\) \{\s*goto (?P<out>\w+);\s*\}\s*'
                  r'goto (?P<loop>\w+);\s*\Z', re.S)


def _reading(text):
    """The operands of a test, so `*(u8 *)(base + (i & 0xFFFF))` and `*(u8 *)(i + base)` compare equal."""
    text = re.sub(r'&\s*0[xX](?:FF|ff){1,2}\b', '', text)
    return sorted(re.findall(r'\w+|[^\w\s()+]', text))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for head in HEAD.finditer(clean, opening + 1, end):
        outer = clean.find('{', head.start())
        inner = head.end() - 1
        outer_end, inner_end = close(clean, outer, '{', '}'), close(clean, inner, '{', '}')
        if not outer_end or not inner_end:
            continue
        body = BODY.fullmatch(clean[inner + 1:inner_end - 1])
        if not body or body['loop'] != head['loop'] or _reading(head['first']) != _reading(body['second']):
            continue
        tail = source[inner_end:outer_end - 1].strip()
        label = re.compile(rf'\s*{body["out"]}:[ \t]*(?:;)?').match(clean, outer_end)
        if not label or not re.search(r'\breturn\b[^;{}]*;\s*\Z', clean[inner_end:outer_end - 1]):
            continue
        n = head['n']
        steps = source[inner + 1:inner + 1 + body.end('steps')]
        step = re.compile(rf'[ \t]*(?<![\w.>]){n}(?:\s*\+=\s*1|\+\+)\s*;[ \t]*\n?')
        if len(step.findall(steps)) != 1:
            continue
        steps = step.sub('', steps)
        if len(re.findall(rf'(?<![\w.>]){n}\b', steps + tail + clean[outer_end:end])):
            continue
        if len(re.findall(rf'\bgoto\s+{head["loop"]}\b', clean[opening:end])) != 1:
            continue
        keep = len(re.findall(rf'\bgoto\s+{body["out"]}\b', clean[opening:end])) > 1
        pad = head['indent']
        moved = [line.strip() for line in steps.strip().splitlines() if line.strip()]
        ending = [line.strip() for line in tail.splitlines() if line.strip()]
        first = source[head.start('first'):head.end('first')]
        lines = [f'{pad}{n} = 0;', f'{pad}while ({first} == 0) {{', f'{pad}    if (++{n} == {head["limit"]}) {{',
                 *(f'{pad}        {line}' for line in ending), f'{pad}    }}',
                 *(f'{pad}    {line}' for line in moved), f'{pad}}}']
        if keep:
            lines.append(f'{body["out"]}:;')
        result.append((FAMILY, source[:head.start()] + '\n'.join(lines) + source[label.end():]))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
