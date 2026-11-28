"""m2c's guarded walk that leaves from the middle, written as the `while` with a `break` it was.

    if (node->parent != 0) {                      while (node->parent != 0) {
loop_9:                                               node = node->parent;
        node = node->parent;                          if (node->kind == 7) {
        if (node->kind != 7) {                            node = node->child;
            if (node->parent != 0) {                      found = 1;
                goto loop_9;                              break;
            }                                         }
        } else {                                  }
            node = node->child;
            found = 1;
        }
    }

The same program. GCC lays the `while` out with its own entry test and moves the arm that leaves out of the loop;
the `for (;;)` with `continue` and a `break` at its end that `goto_backward_loop` writes keeps the repeated test in
the body, so the code differs.

Measured on a 293-instruction N64 object update (SN gcc 2.8.1, `-G0 -mips3 -O2 -mgas -mfp64`): from the machine draft
the `while` took 7285 -> 6350 (`goto_backward_loop` 6880), and with the function's other repairs it was exact where
the `for (;;)` stood at 720.

goto_walk_break
    `if (c) { L: S; if (t) { if (c) goto L; } else { F; } }` (or the arms the other way round) with the two `c` the
    same test and no other jump to `L`: `while (c) { S; if (!t) { F; break; } }`. `S` is plain assignments and calls.

A candidate rewrite; the exact judge decides.
"""
import re

from .branch_polarity_repairs import negate_any
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'goto_walk_break'
FAMILIES = (FAMILY,)
LIMIT = 8

_HEAD = re.compile(r'(?<![\w])if\s*(?=\()')
_LABEL = re.compile(r'\s*\{\s*([A-Za-z_]\w*)\s*:(?!:)')
_SPECIAL = re.compile(r'[{}:?]|\b(?:goto|break|continue|case|default|if|for|while|do|switch)\b')


def _squash(text):
    return re.sub(r'\s+', '', text)


def _if(clean, at):
    """(condition start, condition end, block open, block end) of the `if (..) {..}` at `at`, else None."""
    head = _HEAD.match(clean, at)
    shut = close(clean, head.end()) if head else None
    brace = re.compile(r'\s*\{').match(clean, shut) if shut else None
    end = close(clean, brace.end() - 1, '{', '}') if brace else None
    return (head.end() + 1, shut - 1, brace.end() - 1, end) if end else None


def _other(clean, end):
    """(open, end) of the braced `else` after a block ending at `end`, else None."""
    found = re.compile(r'\s*else\s*\{').match(clean, end)
    stop = close(clean, found.end() - 1, '{', '}') if found else None
    return (found.end() - 1, stop) if stop else None


def _again(clean, start, stop, condition, label):
    """Whether clean[start:stop] is only `if (condition) { goto label; }`."""
    text = clean[start:stop]
    at = len(text) - len(text.lstrip())
    found = _if(text, at)
    if not found or text[found[3]:].strip():
        return False
    return (_squash(text[found[0]:found[1]]) == condition
            and _squash(text[found[2] + 1:found[3] - 1]) == f'goto{label};')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    result = []
    for hit in _HEAD.finditer(clean, span[0], span[1]):
        outer = _if(clean, hit.start())
        if not outer or re.match(r'\s*else\b', clean[outer[3]:]) or re.search(r'\belse\s*$', clean[:hit.start()]):
            continue
        labelled = _LABEL.match(clean, outer[2])
        if not labelled:
            continue
        label = labelled[1]
        if len(re.findall(rf'\bgoto\s+{label}\b', clean[span[0]:span[1]])) != 1:
            continue
        test = _HEAD.search(clean, labelled.end(), outer[3])
        inner = _if(clean, test.start()) if test else None
        if not inner or _SPECIAL.search(clean, labelled.end(), test.start()):
            continue
        other = _other(clean, inner[3])
        if not other or clean[other[1]:outer[3] - 1].strip():
            continue
        condition = _squash(clean[outer[0]:outer[1]])
        # `c` is evaluated at the loop's top either way; a call or a step in it would not be the same program
        if re.search(r'\+\+|--|(?<![=!<>])=(?!=)', condition):
            continue
        then, fallback = (inner[2] + 1, inner[3] - 1), (other[0] + 1, other[1] - 1)
        asked = source[inner[0]:inner[1]]
        if _again(clean, *then, condition, label):
            leave, test_text = fallback, negate_any(asked)
        elif _again(clean, *fallback, condition, label):
            leave, test_text = then, asked.strip()
        else:
            continue
        if not test_text or re.search(r'\b(?:goto|break|continue|case|default)\b|[A-Za-z_]\w*\s*:(?!:)\s',
                                      clean[leave[0]:leave[1]]):
            continue
        start = hit.start()
        line = source[source.rfind('\n', 0, start) + 1:start]
        indent = re.match(r'[ \t]*', line)[0]
        inside, deeper = indent + '    ', indent + '        '
        body = ''.join(f'{inside}{text.strip()}\n' for text in source[labelled.end():test.start()].splitlines()
                       if text.strip())
        left = ''.join(f'{deeper}{text.strip()}\n' for text in source[leave[0]:leave[1]].splitlines() if text.strip())
        loop = (f'while ({source[outer[0]:outer[1]]}) {{\n{body}{inside}if ({test_text}) {{\n{left}'
                f'{deeper}break;\n{inside}}}\n{indent}}}')
        result.append((FAMILY, source[:start] + loop + source[outer[3]:]))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
