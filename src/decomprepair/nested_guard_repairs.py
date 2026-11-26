"""`if ((A) && (B)) { ... }` as two nested `if`s.

Written with `&&`, gcc 2.7.2 may turn two tests of one value into flag arithmetic: an N64 function's
`if ((slot != -1) && (slot >= 0))` came out as `nor`/`sltu`/`srl`/`and` and one branch, where the game branched twice
(`beql` then `bltz`). As `if (slot != -1) { if (slot >= 0) { ... } }` it was exact. Offered for an `if` with no `else`
whose condition is exactly two `&&` operands; the meaning is the same (`&&` short-circuits the same way).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'nested_guard'
FAMILIES = (FAMILY,)


def _python_operands(condition):
    """The two top-level `&&` operands of a condition, or None."""
    depth, cut = 0, []
    for i, ch in enumerate(condition):
        depth += (ch == '(') - (ch == ')')
        if depth == 0 and condition.startswith('&&', i):
            cut.append(i)
    if len(cut) != 1 or '||' in re.sub(r'\([^()]*\)', '', condition):
        return None
    return condition[:cut[0]].strip(), condition[cut[0] + 2:].strip()


_operands = _python_operands
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _operands(condition):
        cut = [i for i in _scan.top_offsets(condition, '&', 1) if condition.startswith('&&', i)]
        if len(cut) != 1 or '||' in re.sub(r'\([^()]*\)', '', condition):
            return None
        return condition[:cut[0]].strip(), condition[cut[0] + 2:].strip()


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
    for hit in re.finditer(r'\bif\s*\(', clean[opening:end]):
        cond_open = opening + hit.end() - 1
        cond_close = close(clean, cond_open)
        if not cond_close:
            continue
        block = re.match(r'\s*\{', clean[cond_close:end])
        if not block:
            continue
        block_open = cond_close + block.end() - 1
        block_close = close(clean, block_open, '{', '}')
        if not block_close or re.match(r'\s*else\b', clean[block_close:end]):
            continue
        parts = _operands(clean[cond_open + 1:cond_close - 1])
        if parts is None or any(re.search(r'\b\w+\s*\(', p) and not p.startswith('(') for p in parts):
            continue
        # the operands as written in the source (the blanked copy has strings and comments masked)
        raw = source[cond_open + 1:cond_close - 1]
        cut = clean[cond_open + 1:cond_close - 1].index(parts[1]) if parts[1] in clean[cond_open + 1:cond_close - 1] else None
        if cut is None:
            continue
        first = raw[:raw.rindex('&&', 0, cut)].strip()
        second = raw[cut:].strip()
        line = source.rfind('\n', 0, opening + hit.start()) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        inner = source[block_open + 1:block_close - 1]
        body = ''.join(('    ' + l if l.strip() else '') + '\n' for l in inner.strip('\n').rstrip().split('\n'))
        text = (source[:opening + hit.start()] + f'if ({first}) {{\n{indent}    if ({second}) {{\n' + body
                + f'{indent}    }}\n{indent}}}' + source[block_close:])
        result.append((FAMILY, text))
        if len(result) >= 4:
            break
    return result

