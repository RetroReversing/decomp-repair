"""Two tests of one value that m2c nested inside each other, written as the `switch` they came from.

    if (g != 0) { r = 0; if (g != 1) { } else { S1 } } else { S0 }
 -> switch (g) { case 0: S0 break; case 1: r = 0; S1 break; default: r = 0; break; }

A two-case `switch` compiles to `beqz`/`li; beq` tests whose arms GCC lays out in case order after the tests; m2c reads it
back as nested `if`s with the arms inside out (the `!= 0` test's `else` is case 0, the inner `!= 1` test's empty
`then` is the default). Written as nested `if`s GCC lays the arms out in the order the `if`s give, so every row after
them moves. On a 1315-instruction KMC GCC 2.7.2 sound-sequence interpreter (`-G0 -mips3 -mgp32 -mfp32 -O2`) the
`switch` took 11300 -> 10360.

`nested_test_switch`
    `if (X != K0) { P if (X != K1) { } else { S1 } } else { S0 }` (or the inner test as `if (X == K1) { S1 }`), `X` a
    name, `K0`/`K1` different literals, `P` statements without blocks, and no `break` or `continue` of the enclosing
    construct in `S0`/`S1`: the `switch` above, with `P` run on the paths that ran it.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'nested_test_switch'
FAMILIES = (FAMILY,)


def _own_breaks(text):
    """Whether `text` has a `break`/`continue` that is not inside a switch or loop of its own."""
    for hit in re.finditer(r'\b(?:break|continue)\b', text):
        depth = 0
        inside = False
        for pos in range(hit.start() - 1, -1, -1):
            if text[pos] == '}':
                depth += 1
            elif text[pos] == '{':
                if depth:
                    depth -= 1
                    continue
                head = text[:pos].rstrip()
                if re.search(r'\bdo$', head) or (hit[0] == 'break' and re.search(r'\bswitch\s*\([^{}]*\)$', head)) \
                        or re.search(r'\b(?:for|while)\s*\([^{}]*\)$', head):
                    inside = True
                    break
        if not inside:
            return True
    return False


def _block(clean, at):
    brace = re.compile(r'\s*\{').match(clean, at)
    if not brace:
        return None
    opening = brace.end() - 1
    end = close(clean, opening, '{', '}')
    return (opening, end) if end else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    results = []
    for outer in re.finditer(r'\bif\s*\(\s*(' + IDENT + r')\s*!=\s*(' + NUMBER + r')\s*\)', clean[part.opening:part.end]):
        start = part.opening + outer.start()
        variable, first = outer[1], outer[2]
        then = _block(clean, part.opening + outer.end())
        if not then:
            continue
        otherwise = re.compile(r'\s*else\b').match(clean, then[1])
        if not otherwise:
            continue
        other = _block(clean, otherwise.end())
        if not other:
            continue
        inside = clean[then[0] + 1:then[1] - 1]
        inner = re.search(r'\bif\s*\(\s*' + re.escape(variable) + r'\s*(!=|==)\s*(' + NUMBER + r')\s*\)', inside)
        if not inner:
            continue
        prefix = inside[:inner.start()]
        if '{' in prefix or '}' in prefix or re.search(r'\b(?:if|while|for|do|switch|goto|return|break|continue)\b', prefix) \
                or re.search(r'\b' + re.escape(variable) + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', prefix):
            continue
        if inner[2] == first:
            continue
        base = then[0] + 1
        inner_then = _block(clean, base + inner.end())
        if not inner_then:
            continue
        if inner[1] == '!=':
            if clean[inner_then[0] + 1:inner_then[1] - 1].strip():
                continue
            inner_else = re.compile(r'\s*else\b').match(clean, inner_then[1])
            if not inner_else:
                continue
            second = _block(clean, inner_else.end())
            if not second:
                continue
            tail = second[1]
        else:
            second = inner_then
            tail = second[1]
            if re.compile(r'\s*else\b').match(clean, tail):
                continue
        if clean[tail:then[1] - 1].strip():
            continue
        first_body = source[other[0] + 1:other[1] - 1]
        second_body = source[second[0] + 1:second[1] - 1]
        if _own_breaks(clean[other[0] + 1:other[1] - 1]) or _own_breaks(clean[second[0] + 1:second[1] - 1]):
            continue
        shared = source[base:base + inner.start()].strip()
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:]).group(0)
        lines = [f'switch ({variable})', f'{indent}{{', f'{indent}  case {first}:', _reindent(first_body, indent + '    '),
                 f'{indent}    break;', '', f'{indent}  case {inner[2]}:']
        if shared:
            lines.append(_reindent(shared, indent + '    '))
        lines += [_reindent(second_body, indent + '    '), f'{indent}    break;']
        if shared:
            lines += ['', f'{indent}  default:', _reindent(shared, indent + '    '), f'{indent}    break;']
        lines.append(f'{indent}}}')
        results.append((FAMILY, edit(source, [(start, other[1], '\n'.join(lines))])))
    return results


def _reindent(text, indent):
    lines = [line.rstrip() for line in text.split('\n')]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    width = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    return '\n'.join(indent + line[width:] if line.strip() else '' for line in lines)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
