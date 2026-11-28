"""A loop's early `continue` that steps the counter first, written as a guard around the rest of the body.

A hand or typed first draft of a `while` loop that skips one entry often steps its counter in the skip and again at the
foot of the body:

    while (more(list[i])) {                    while (more(list[i])) {
        if (mode == 7 && i == 1) {                 if (!(mode == 7 && i == 1)) {
            i++;                                       draw(list[i]);
            continue;                              }
        }                              ->          i++;
        draw(list[i]);                         }
        i++;
    }

Both run the same statements in the same order. The compiler does not lay them out the same: the first has two steps
and two jumps back, which it merges differently from one step the skip branches to. A 437-instruction N64 menu routine
(SN GCC 2.8.1) went 870 -> 0 with the guard (4040 -> 3020 on the draft without its other edit).

The guard is also offered for a bare `if (c) continue;` followed by the rest of the body. Only `==` and `!=` are
turned into each other; every other test is negated as `!(c)`, so a floating-point comparison keeps its meaning with a
NaN. Nothing is offered when the skip has an `else`, when the statements before `continue` are not the ones that end
the body, or when the rest of the body declares a name the step uses."""
import re

from .c_scan import close, own_loop_statements
from .csource import _blank, find

FAMILY = 'continue_step_guard'
FAMILIES = (FAMILY,)
LIMIT = 4
LOOP = re.compile(r'\b(for|while|do)\b')
EQUALITY = re.compile(r'^([^=!<>&|?;]+?)(==|!=)([^=!<>&|?;]+)$')
NOT_A_STEP = re.compile(r'["\']|\b(?:if|else|for|while|do|switch|case|default|goto|break|continue|return)\b|[{}:?#]')


def _bodies(clean, span):
    """(opening, closing) braces of every braced loop body of the function."""
    for loop in LOOP.finditer(clean, span[0], span[1]):
        at = loop.end()
        if loop[1] != 'do':
            at = clean.find('(', at)
            end = close(clean, at, '(', ')') if at >= 0 else -1
            if end < 0:
                continue
            at = end + 1
        while at < span[1] and clean[at].isspace():
            at += 1
        if clean[at:at + 1] != '{':
            continue  # (`do {...} while (c);`: the closing `while` has no body of its own)
        end = close(clean, at)
        if end >= 0:
            yield at, end


def _negated(condition):
    text = condition.strip()
    if text.startswith('!') and text[1:].lstrip().startswith('('):
        inner = text[1:].lstrip()
        if close(inner, 0, '(', ')') == len(inner) - 1:
            return inner[1:-1].strip()
    hit = EQUALITY.match(text)
    if hit and hit[1].count('(') == hit[1].count(')') and hit[3].count('(') == hit[3].count(')'):
        return f'{hit[1].strip()} {"!=" if hit[2] == "==" else "=="} {hit[3].strip()}'
    if re.match(r'^!?\s*[A-Za-z_]\w*$', text):
        return text[1:].strip() if text.startswith('!') else f'!{text}'
    return f'!({text})'


def _declares(rest, step):
    for name in set(re.findall(r'[A-Za-z_]\w*', step)):
        if re.search(rf'(?:^|[;{{}}])\s*[A-Za-z_]\w*[\s*]+(?:[^;{{}}()]*,[\s*]*)?{name}\b\s*[=;,\[)]', rest):
            return True
    return False


def _guard(source, clean, opening, closing):
    """The guarded rewrites of the loop whose body is clean[opening:closing + 1]."""
    for at in own_loop_statements(clean, opening + 1, closing, 'continue'):
        skips = [hit for hit in re.finditer(r'\bif\s*\(', clean[opening + 1:at])]
        if not skips:
            continue
        start = opening + 1 + skips[-1].start()
        paren = opening + 1 + skips[-1].end() - 1
        paren_end = close(clean, paren, '(', ')')
        if paren_end < 0 or paren_end >= at:
            continue
        before = clean[opening:start].rstrip()
        if before[-1] not in ';{}' or clean[opening + 1:start].count('{') != clean[opening + 1:start].count('}'):
            continue  # not a statement of the body itself
        arm = re.compile(r'\s*(\{)?\s*').match(clean, paren_end + 1)
        step = clean[arm.end():at].strip()
        if step and (not arm[1] or not step.endswith(';') or NOT_A_STEP.search(step)):
            continue
        if '"' in source[arm.end():at] or "'" in source[arm.end():at]:
            continue
        tail = re.compile(r'continue\s*;\s*' + (r'\}' if arm[1] else '')).match(clean, at)
        if not tail or re.match(r'\s*else\b', clean[tail.end():closing]):
            continue
        body = clean[tail.end():closing].rstrip()
        step_start = len(body)
        if step:
            words = re.findall(r'\w+|\+\+|--|[^\w\s]', step)
            last = re.search(r'\s*'.join(map(re.escape, words)) + r'$', body)
            if not last or '"' in source[tail.end() + last.start():closing] or "'" in source[tail.end() + last.start():closing]:
                continue
            step_start = last.start()
        rest = body[:step_start].rstrip()
        if not rest or rest[-1] not in ';}' or rest.count('{') != rest.count('}') or _declares(rest, step):
            continue
        rest_end = tail.end() + len(rest)
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
        inner = source[tail.end():rest_end].strip('\n').rstrip()
        inner = '\n'.join('    ' + line if line.strip() else line for line in inner.split('\n'))
        condition = _negated(source[paren + 1:paren_end])
        yield (source[:start] + f'if ({condition}) {{\n{inner}\n{indent}}}' + source[rest_end:])


def variants(source, name):
    span = find(source, name)
    if not span or 'continue' not in source[span[0]:span[1]]:
        return []
    clean = _blank(source)
    if re.search(r'^[ \t]*#|\b(?:asm|__asm__)\b', clean[span[0]:span[1]], re.M):
        return []
    out = []
    for opening, closing in _bodies(clean, span):
        out.extend(_guard(source, clean, opening, closing))
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 66}
