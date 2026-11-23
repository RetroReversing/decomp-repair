"""A guard written the way the original split it: the load before its last test, and the loop bound copied after the guard.

Two shapes a target-picking loop (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`, an N64 actor list) needed together, each
worse alone (1015 -> 1125 and 1015 -> 1200), 705 combined, on a 445-instruction function:

* `if (A && B && C) { x = load; ... }` where `C` is a float compare. The first scheduler only fills the compare's two-cycle
  shadow with an instruction of the same basic block, so the target's `lw $a0, 0x6c($a1)` sits between `c.le.s` and its
  branch; written as `if (A && B) { x = load; if (C) { ... } }` the load is in the block of the compare.
* `T n = global; ... if (k < n) { ... while (i < n); }` with the guard reading the global itself and `n` assigned inside
  the guard (`if (k < global) { n = global; ... }`): the loop's bound is then a copy of the guard's load (`move $a1, $v1`
  after the branch), a pseudo of its own, where one local used by both is a single pseudo and the copy is gone.

The load is moved ahead of a test, so it runs when the test fails; the family proposes that, and the judge (and the
reader of the diff) decides whether the guarded pointers are valid there. A candidate for the exact judge, never a verdict.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY_LOAD = 'guard_load_first'
FAMILY_BOUND = 'guard_bound_copy'
FAMILY_BOTH = 'guard_load_split'
FAMILIES = (FAMILY_LOAD, FAMILY_BOUND, FAMILY_BOTH)
LIMIT = 6
_EXTERN = re.compile(r'^[ \t]*extern[ \t]+(?:volatile[ \t]+)?[A-Za-z_][\w \t]*?[ \t]+([A-Za-z_]\w*)[ \t]*;', re.M)
_BOUND = re.compile(r'(?m)^([ \t]*)((?:unsigned[ \t]+|signed[ \t]+)?[A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*=[ \t]*([A-Za-z_]\w*)[ \t]*;[ \t]*\n')
_IF = re.compile(r'\bif\s*\(')
_LOAD = re.compile(r'\s*([A-Za-z_]\w*)\s*=\s*([^;{}]+);')


def _unwrap(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _conjuncts(condition):
    """The top-level `&&` operands of a condition, outer parentheses and nested left-grouped chains opened."""
    text = _unwrap(condition)
    depth, cut = 0, None
    for pos, char in enumerate(text):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif depth == 0 and text.startswith('&&', pos) and (pos == 0 or text[pos - 1] != '&'):
            cut = pos
    if cut is None:
        return [text]
    return _conjuncts(text[:cut]) + [text[cut + 2:].strip()]


def _bodies(part):
    """Every `if (cond) { ... }` of the function without an `else`: (if start, cond start, cond end, brace, end of body)."""
    clean = part.clean
    for hit in _IF.finditer(clean, part.opening, part.end):
        paren = hit.end() - 1
        stop = close(clean, paren)
        if not stop:
            continue
        brace = clean.find('{', stop)
        if brace < 0 or clean[stop:brace].strip():
            continue
        end = close(clean, brace, '{', '}')
        if not end or re.match(r'\s*else\b', clean[end:end + 20]):
            continue
        yield hit.start(), paren + 1, stop - 1, brace, end


def _plain_load(text):
    """A right-hand side that only reads memory: dereferences and the FIELD macros, no call, step or assignment."""
    flat = re.sub(r'\b(?:M2C_)?FIELD\s*\(', '(', text)
    return ('*' in text or 'FIELD' in text) and not re.search(r'\+\+|--|(?<![=!<>])=(?!=)|\b[A-Za-z_]\w*\s*\(', flat)


def _load_first(source, part):
    for start, cond_start, cond_stop, brace, end in _bodies(part):
        operands = _conjuncts(source[cond_start:cond_stop])
        first = _LOAD.match(part.clean, brace + 1)
        if len(operands) < 2 or not first or not _plain_load(first[2]):
            continue
        last = operands[-1]
        if not re.search(r'[<>]|==|!=|^\s*!', last) or re.search(rf'\b{re.escape(first[1])}\b', last):
            continue
        prefix = ' && '.join(f'({op})' for op in operands[:-1]) if len(operands) > 2 else operands[0]
        statement = source[brace + 1:first.end()].strip()
        rest = source[first.end():end - 1]
        text = f'{prefix})\n    {{\n      {statement}\n      if ({last})\n      {{{rest}      }}\n    }}'
        return [(cond_start, end, text)]
    return []


def _bound_copy(source, part, scalars):
    edits = []
    for hit in _BOUND.finditer(part.clean, part.opening, part.end):
        indent, typ, var, glob = hit.groups()
        if glob not in scalars or var == glob:
            continue
        for start, cond_start, cond_stop, brace, end in _bodies(part):
            if start < hit.end() or start - hit.end() > 160:
                continue
            condition = source[cond_start:cond_stop]
            if not re.search(rf'\b{re.escape(var)}\b', condition) or not re.search(rf'\b{re.escape(var)}\b', source[brace:end]):
                break
            text = re.sub(rf'\b{re.escape(var)}\b', glob, condition)
            edits += [(hit.start(), hit.end(), f'{indent}{typ} {var};\n'), (cond_start, cond_stop, text),
                      (brace + 1, brace + 1, f'\n{indent}  {var} = {glob};')]
            return edits
    return edits


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    scalars = {hit[1] for hit in _EXTERN.finditer(part.clean[:part.opening])}
    load = _load_first(source, part)
    bound = _bound_copy(source, part, scalars)
    result = []
    for family, edits in ((FAMILY_LOAD, load), (FAMILY_BOUND, bound), (FAMILY_BOTH, load + bound if load and bound else [])):
        if edits:
            changed = edit(source, edits)
            if changed != source:
                result.append((family, changed))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 100}  # the registry: no caller wiring (registry.py)
