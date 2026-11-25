"""Two loop-depth weight rewrites from a large collision sweep's last rows (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`).

flow.c adds a pseudo's loop depth to its reference count at every use (`reg_n_refs += loop_depth`), and both allocators
rank by `floor_log2 (refs) * refs / life`: global.c truncated to an integer (ties go to the lower pseudo number),
local-alloc per quantity (a quantity's refs summed over the pseudos tied into it). Loop notes, from a real `do`/`while`
or an empty `do { } while (0)`, decide the depth. Measured on a 2,267-instruction collision sweep with the exact judge:

- `do_while_goto_loop`: `do { B } while (C);` written as m2c's goto loop, `L: B if (C) { goto L; }` (no loop notes:
  one level shallower). The sweep's u16 triangle loop was a `do`/`while` and its sibling u8 loop a goto loop; their
  plane dot products are the same text, but at depth 6 the product quantity's refs (36) crossed a power of two
  (`floor_log2` 5, against 4 at depth 5) and local-alloc gave it `$f4` where the target (and the u8 site) has `$f6`.
  As a goto loop the u16 site matched (30 -> 30 with the next step's tie, then 0).
- `parameter_read_scope`: one statement that reads a parameter (and no other parameter) wrapped in `do { } while (0)`,
  the one-statement scope weighting that read one depth deeper. Two float parameters with 29 refs each, live 3456 and
  3454 insns, tied in global.c at 335 (`4 * 29 * 10000 / live`, truncated) and the lower pseudo (the earlier
  parameter) took the callee-saved register the target gives the later one; the clamp `t = y + arg7; if (t < c) c = t;`
  in a scope made arg7's refs 30 and the match (30 -> 0). Scaffolding (an empty loop): report it when it decides a match.

Candidate rewrites; the exact judge decides each.
"""
import re

from .integer_repair_support import IDENT, view

GOTO_LOOP = 'do_while_goto_loop'
PARAM_SCOPE = 'parameter_read_scope'
FAMILIES = (GOTO_LOOP, PARAM_SCOPE)
LIMIT = 12


def _python_close(text, opening):
    depth = 0
    for i in range(opening, len(text)):
        if text[i] in '({[':
            depth += 1
        elif text[i] in ')}]':
            depth -= 1
            if depth == 0:
                return i
    return -1


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(text, opening):
        found = _scan.close_pairs(text, opening, '({[', ')}]', False, False, -1)
        return _python_close(text, opening) if found is NotImplemented else found


def _goto_loops(source, part):
    clean = part.clean
    out = []
    used = set(re.findall(rf'\b({IDENT})\s*:(?!:)', clean))
    n = 0
    for hit in re.finditer(r'\bdo\s*{', clean[:part.end]):
        if hit.start() < part.opening:
            continue
        brace = hit.end() - 1
        end = _close(clean, brace)
        tail = re.compile(r'\s*while\s*\(').match(clean, end + 1) if end > 0 else None
        if not tail:
            continue
        paren = tail.end() - 1
        stop = _close(clean, paren)
        semi = re.compile(r'\s*;').match(clean, stop + 1) if stop > 0 else None
        cond = clean[paren + 1:stop].strip() if stop > 0 else ''
        if not semi or not cond or re.fullmatch(r'\(*\s*0\s*\)*', cond):
            continue
        body = clean[brace + 1:end]
        if re.search(r'\b(?:break|continue)\b', body):
            continue
        while f'loop_{n}' in used:
            n += 1
        label = f'loop_{n}'
        used.add(label)
        text = (source[:hit.start()] + f'{label}: {{' + source[brace + 1:end] + '} if (' + source[paren + 1:stop]
                + f') {{ goto {label}; }}' + source[semi.end():])
        out.append((GOTO_LOOP, text))
    return out


def _params(clean, part):
    head = clean[:part.opening]
    paren = head.rfind(')')
    start = head.rfind('(', 0, paren)
    depth = 0
    for i in range(paren, -1, -1):
        if head[i] == ')':
            depth += 1
        elif head[i] == '(':
            depth -= 1
            if depth == 0:
                start = i
                break
    names = []
    for piece in head[start + 1:paren].split(','):
        found = re.findall(IDENT, piece)
        if found and found[-1] != 'void':
            names.append((found[-1], bool(re.search(r'\b(?:f32|f64|float|double)\b', piece)) and '*' not in piece))
    return names


def _param_scopes(source, part, floats_only=False):
    clean = part.clean
    typed = _params(clean, part)
    params = [p for p, _ in typed]
    if floats_only:
        typed = [(p, f) for p, f in reversed(typed) if f]
    out = []
    statement = re.compile(rf'(?<=[;{{}}])(\s*)({IDENT}\s*=[^;{{}}]*;)(\s*if\s*\()?')
    for param, _ in typed:
        others = [p for p in params if p != param]
        hits = [m for m in statement.finditer(clean, part.opening, part.end)
                if re.search(rf'\b{re.escape(param)}\b', m[2].split('=', 1)[1])
                and not any(re.search(rf'\b{re.escape(o)}\b', m[2]) for o in others)
                and not re.match(rf'\s*{re.escape(param)}\b', m[2])]
        for m in hits[:2] + hits[-2:]:
            lo = m.start(2)
            hi = m.end(2)
            if m[3]:
                paren = clean.index('(', m.end(2))
                stop = _close(clean, paren)
                arm = re.compile(r'\s*{').match(clean, stop + 1) if stop > 0 else None
                if arm:
                    close = _close(clean, arm.end() - 1)
                    if close > 0 and not re.compile(r'\s*else\b').match(clean, close + 1):
                        hi = close + 1
            text = source[:lo] + 'do { ' + source[lo:hi] + ' } while (0);' + source[hi:]
            if all(text != t for _, t in out):
                out.append((PARAM_SCOPE, text))
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    loops = _goto_loops(source, part)
    out = (loops + _param_scopes(source, part))[:LIMIT * 2]
    # The pair that decided the match was worse at its first step (the goto loop's shallower refs re-tied two float
    # parameters, 30 -> 1401), so each loop is also offered with the float-parameter scopes of its own source.
    for _, loop in loops[:4]:
        inner = view(loop, name)
        if inner:
            out.extend(_param_scopes(loop, inner, floats_only=True)[:4])
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring
