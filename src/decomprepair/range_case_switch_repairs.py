"""m2c's range test and empty arm for a `switch` whose low cases share one body, written back as the `switch`.

A `switch` on an unsigned value with cases 0..K-1 sharing a body and case K another becomes a range test and a compare,
which m2c reads back as

    if (x >= 4U) {
        if (x != 4) {

        } else {
            B;
        }
    } else {
        A;
    }

An N64 function was 95.4% so, 93.2% as `if (x < 4U) A; else if (x == 4) B;`, and exact as `switch (x) { case 0: case 1:
case 2: case 3: A; break; case 4: B; break; }`. Offered for K up to 8.
"""
import re

from .csource import _blank, find
from .integer_repair_support import locals_for, view
from .pattern_repairs import close
from .switch_default_tail_repairs import _has_outer_break

FAMILY = 'range_case_switch'
JOINED_FAMILY = 'joined_range_case_switch'
BOUNDED_FAMILY = 'bounded_mode_switch'
FAMILIES = (FAMILY, JOINED_FAMILY, BOUNDED_FAMILY)

IDENT = r'[A-Za-z_]\w*'
SHAPE = re.compile(
    r'(?m)^(?P<indent>[ \t]*)if\s*\(\s*(?P<x>' + IDENT + r')\s*>=\s*(?P<k>\d+)[uU]\s*\)\s*\{\s*\n'
    r'[ \t]*if\s*\(\s*(?P=x)\s*!=\s*(?P=k)[uU]?\s*\)\s*\{\s*\}\s*else\s*\{(?P<b>[^{}]*)\}\s*\n'
    r'[ \t]*\}\s*else\s*\{(?P<a>[^{}]*)\}[ \t]*\n')


# The middle range runs one case, and the two bounding values share a separate case.
# Some drafts duplicate the low value's goto under another condition.
DECIMAL = r'(?:0|[1-9]\d*)'
JOINED_SHAPE = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)if\s*\(\s*(?P<x>{IDENT})\s*<\s*(?P<hi>{DECIMAL})\s*\)\s*\{{\s*'
    rf'if\s*\(\s*(?P=x)\s*<\s*(?P<lo>{DECIMAL})\s*\)\s*\{{\s*'
    rf'if\s*\(\s*(?P=x)\s*!=\s*(?P<lower>{DECIMAL})\s*\)\s*\{{\s*\}}\s*else\s*')
MIDDLE = re.compile(r'\s*\}\s*else\s*\{')
UPPER = re.compile(rf'\s*\}}\s*else\s*if\s*\(\s*({IDENT})\s*==\s*({DECIMAL})\s*\)\s*\{{')
LABEL = re.compile(r'\s*(' + IDENT + r')\s*:(?!:)')
JUMP = re.compile(r'\s*\{\s*goto\s+(' + IDENT + r')\s*;\s*\}')
DUPLICATE_JUMP = re.compile(r'if\s*\(')
OTHERWISE = re.compile(r'\s*else')


def _joined_jump(source, clean, start):
    plain = JUMP.match(clean, start)
    if plain:
        return plain[1], plain.end(), None
    duplicate = DUPLICATE_JUMP.match(clean, start)
    cond = close(clean, duplicate.end() - 1) if duplicate else None
    first = JUMP.match(clean, cond) if cond else None
    otherwise = OTHERWISE.match(clean, first.end()) if first else None
    other = JUMP.match(clean, otherwise.end()) if otherwise else None
    if other and first[1] == other[1]:
        return first[1], other.end(), source[duplicate.end():cond - 1]
    return None


def _joined_variants(source, name, clean, opening, end):
    declared = None
    for hit in JOINED_SHAPE.finditer(clean, opening, end):
        if declared is None:
            part = view(source, name)
            declared = {item['name']: item.start() for item in locals_for(part)} if part else {}
        if declared.get(hit['x'], end) >= hit.start():
            continue
        low, high, lower = (int(hit[key]) for key in ('lo', 'hi', 'lower'))
        if lower != low - 1 or not 1 <= high - low <= 4:
            continue
        jump = _joined_jump(source, clean, hit.end())
        middle = MIDDLE.match(clean, jump[1]) if jump else None
        middle_end = close(clean, middle.end() - 1, '{', '}') if middle else None
        upper = UPPER.match(clean, middle_end) if middle_end else None
        upper_end = close(clean, upper.end() - 1, '{', '}') if upper else None
        if not upper_end or upper_end > end or upper[1] != hit['x'] or int(upper[2]) != high:
            continue
        join = LABEL.match(clean, upper.end())
        if not join or join[1] != jump[0] or re.match(r'\s*else\b', clean[upper_end:]):
            continue
        middle_code = clean[middle.end():middle_end - 1]
        upper_code = clean[join.end():upper_end - 1]
        if not middle_code.strip() or not upper_code.strip():
            continue
        if any(_has_outer_break(body) or re.search(r'(?m)^\s*#', body) for body in (middle_code, upper_code)):
            continue
        indent = hit['indent']
        middle_labels = ''.join(f'{indent}    case {n}:\n' for n in range(low, high))
        condition = f'{indent}        (void)({jump[2]});\n' if jump[2] is not None else ''
        # Keep both original local scopes and the old label. The lower case alone used to evaluate
        # the redundant condition, so it still does, including any volatile reads or calls.
        upper_arm = (f'{indent}    case {lower}:\n{condition}{indent}    case {high}: {{'
                     f'{source[upper.end():upper_end - 1].rstrip()}\n{indent}        break;\n{indent}    }}\n')
        middle_arm = (f'{middle_labels[:-1]} {{'
                      f'{source[middle.end():middle_end - 1].rstrip()}\n{indent}        break;\n{indent}    }}\n')
        for arms in (upper_arm + middle_arm, middle_arm + upper_arm):
            text = f'{indent}switch ({hit["x"]}) {{\n{arms}{indent}}}'
            yield JOINED_FAMILY, source[:hit.start()] + text + source[upper_end:]


_GUARD = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)if\s*\(\s*\(\s*\(\s*(?P<name>{IDENT})\s*>=\s*0\s*\)'
    r'\s*&&\s*\(\s*(?P=name)\s*>=\s*(?P<low>[1-8])\s*\)\s*\)'
    r'\s*&&\s*\(\s*(?P=name)\s*<\s*(?P<high>[2-9])\s*\)\s*\)\s*{')


def _bounded_variants(source, name, clean, opening, end):
    part = view(source, name)
    if not part:
        return
    declared = {entry['name']: entry.start() for entry in locals_for(part)}
    for hit in _GUARD.finditer(clean, opening, end):
        if declared.get(hit['name'], end) >= hit.start():
            continue
        low, high = int(hit['low']), int(hit['high'])
        if not 1 <= high-low <= 4:
            continue
        body_at = hit.end() - 1
        body_end = close(clean, body_at, '{', '}')
        if not body_end or re.match(r'\s*else\b', clean[body_end:end]):
            continue
        body = clean[body_at+1:body_end-1]
        if not body.strip() or _has_outer_break(body) or re.search(r'\b(?:case|default)\b', body):
            continue
        indent = hit['indent']
        lower = ' '.join(f'case {value}:' for value in range(low))
        active = ' '.join(f'case {value}:' for value in range(low, high))
        region = (f'{indent}switch ({hit["name"]}) {{\n'
                  f'{indent}    {lower} break;\n'
                  f'{indent}    {active} {{{source[body_at+1:body_end-1]}}} break;\n'
                  f'{indent}    default: break;\n{indent}}}')
        yield BOUNDED_FAMILY, source[:hit.start()] + region + source[body_end:]


def _body(text, indent):
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return ''.join(f'{indent}    {line}\n' for line in lines) + f'{indent}    break;\n'


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
    for hit in SHAPE.finditer(clean, opening, end):
        k = int(hit['k'])
        if not 1 <= k <= 8:
            continue
        indent = hit['indent']
        a = source[hit.start('a'):hit.end('a')]
        b = source[hit.start('b'):hit.end('b')]
        low = ' '.join(f'case {i}:' for i in range(k))
        text = (f'{indent}switch ({hit["x"]}) {{\n{indent}{low}\n{_body(a, indent)}'
                f'{indent}case {k}:\n{_body(b, indent)}{indent}}}\n')
        result.append((FAMILY, source[:hit.start()] + text + source[hit.end():]))
    return (list(_bounded_variants(source, name, clean, opening, end))[:4]
            + result + list(_joined_variants(source, name, clean, opening, end))[:4])
