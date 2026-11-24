"""A `default:` label m2c put in one arm's `else`, written as the arm falling through into its own `default:` arm.

    case 2: if (c) { t = f(); r = 0; ... } else { default: block_205: r = 0; } break;
 -> case 2: if (c) { t = f(); r = 0; ... }
    default: block_205: r = 0; break;

m2c finds the switch's default code in the middle of an arm and opens it inside the arm's `else`. The game wrote the arm
to fall through into `default:` (the arm's own path ends by setting the same result), so the default's code is the
arm's tail, and every other arm that m2c joined to it with `goto` reaches the same block. With the label inside the
`else`, GCC lays the default block out inside the arm and jump2 cross-jumps the next arm (identical but for one
field offset) into this one, which the target does not; on a 1315-instruction KMC GCC 2.7.2 sound-sequence
interpreter (`-G0 -mips3 -mgp32 -mfp32 -O2`) the fall-through took 13735 -> 11545.

`default_label_fallthrough`
    A top-level `if (C) { T } else { default: [L:] V = K; }` that is the last statement of a `case` arm before its
    `break;`, where `T` sets `V = K;` at its top level and then never writes `V`, and has no `break`, `continue`,
    `goto` or `return`: the `else` goes, and `default: [L:] V = K; break;` follows the arm (after the arm's own
    block, when the arm is one). The judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'default_label_fallthrough'
FAMILIES = (FAMILY,)
VALUE = r'(?:-?\s*' + NUMBER + r'|NULL)'


def _top_level_assignments(text, name):
    depth = 0
    found = []
    for hit in re.finditer(r'[{}]|\b' + re.escape(name) + r'\s*=(?!=)\s*([^;]*);', text):
        if hit[0] == '{':
            depth += 1
        elif hit[0] == '}':
            depth -= 1
        else:
            found.append((depth, hit.start(), re.sub(r'\s+', '', hit[1])))
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    results = []
    for hit in re.finditer(r'\belse\s*\{\s*default\s*:', clean[part.opening:part.end]):
        else_at = part.opening + hit.start()
        block = part.opening + hit.end() - len(re.search(r'\{\s*default\s*:$', hit[0])[0])
        block_end = close(clean, block, '{', '}')
        if not block_end:
            continue
        inner = clean[block + 1:block_end - 1]
        body = re.fullmatch(r'\s*default\s*:\s*((?:' + IDENT + r'\s*:(?!:)\s*)*)(' + IDENT + r')\s*=\s*(' + VALUE
                            + r')\s*;\s*', inner)
        if not body:
            continue
        labels, variable, value = body[1], body[2], re.sub(r'\s+', '', body[3])
        # the `if` this `else` belongs to: `if (C) { T }` just before it
        then_end = else_at
        while then_end > 0 and clean[then_end - 1].isspace():
            then_end -= 1
        if clean[then_end - 1] != '}':
            continue
        depth = 0
        then_open = None
        for pos in range(then_end - 1, part.opening, -1):
            if clean[pos] == '}':
                depth += 1
            elif clean[pos] == '{':
                depth -= 1
                if depth == 0:
                    then_open = pos
                    break
        if then_open is None:
            continue
        head = clean[:then_open].rstrip()
        if not head.endswith(')'):
            continue
        level = 0
        paren = None
        for pos in range(len(head) - 1, -1, -1):
            level += (head[pos] == ')') - (head[pos] == '(')
            if level == 0:
                paren = pos
                break
        if paren is None or not re.search(r'\bif\s*$', clean[:paren]):
            continue
        then = clean[then_open + 1:then_end - 1]
        if re.search(r'\b(?:break|continue|goto|return)\b', then):
            continue
        writes = _top_level_assignments(then, variable)
        tops = [w for w in writes if w[0] == 0 and w[2] == value]
        if not tops or any(w[1] > tops[-1][1] for w in writes if w is not tops[-1]):
            continue
        if re.search(r'(?:\+\+|--)\s*' + re.escape(variable) + r'\b|\b' + re.escape(variable) + r'\s*(?:\+\+|--|[-+*/%&|^]=)', then):
            continue
        after = re.match(r'\s*break\s*;', clean[block_end:part.end])
        if not after:
            continue
        stop = block_end + after.end()
        closing = re.match(r'\s*\}', clean[stop:part.end])
        if closing and re.search(r'\bcase\b[^:;{}]*:\s*\{', clean[part.opening:else_at].rsplit('break', 1)[-1]):
            stop += closing.end()
        elif closing:
            continue
        indent = '      '
        label_text = ''.join(f'{indent}  {label.strip()}\n' for label in re.findall(IDENT + r'\s*:', labels))
        tail = f'\n{indent}default:\n{label_text}{indent}  {variable} = {body[3].strip()};\n{indent}  break;\n'
        text = edit(source, [(then_end, block_end, ''), (stop, stop, tail)])
        # the arm's own `break;` goes: the arm now falls through into `default:`
        text = _drop_break(text, then_end)
        results.append((FAMILY, text))
    return results


def _drop_break(text, at):
    hit = re.compile(r'\s*break\s*;').match(text, at)
    return text[:at] + text[hit.end():] if hit else text


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
