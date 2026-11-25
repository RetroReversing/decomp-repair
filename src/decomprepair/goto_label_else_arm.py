"""goto_label_else_arm: an early arm that jumps to a label deep in the code after it, written as that code's `else`.

m2c reads a block that the compiler laid out *after* the code it skips as an early arm that jumps forward:

    if (hit(...) != 0) { X; goto join; }
    Y ... { ...; join: S; } }          // the label's run S ends its block, and nothing follows to Y's end

The original wrote the two paths as one two-way branch with the hit path last, each with its own copy of the
shared tail; the final jump pass cross-jumps the identical tails again:

    if (!(hit(...) != 0)) { Y ... { ...; S; } } else { X; S; }

GCC 2.7.2 emits an `if`'s then-arm in line and the else-arm after it, so the early arm's spelling puts X's code
first (where the target has Y's) and the shared run in the middle of Y. A KMC-compiled N64 collision routine
(`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 2,267 instructions) had two such sites, a triangle-hit arm
jumping into the closest-edge push-out: 24406 -> 22230 for the first, 18762 for both. The target's `bnel` to the
hit block placed after the other path is the evidence.

Preconditions, so the rewrite keeps the meaning: the `if` has no `else` and its arm ends in the only `goto L;`; the
label sits in the statements after the `if` in the same block, its run S goes to the end of the label's block, and
from there only closing braces lead to the end of the `if`'s block (falling out of S ends the same way as the
`goto`); S holds no labels, declarations or loops. Each site alone, and all sites together, are offered."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'goto_label_else_arm'
FAMILIES = (FAMILY,)
LIMIT = 6

IDENT = r'[A-Za-z_]\w*'
_BAD_RUN = re.compile(rf'\b(?:case|default|while|for|do|switch|goto|return|break|continue)\b|(?:^|[;{{}}])\s*{IDENT}\s*:(?!:)')
_DECL = re.compile(rf'(?:^|[;{{}}])\s*(?:const\s+|volatile\s+|unsigned\s+|signed\s+|struct\s+)*{IDENT}\s+\**\s*{IDENT}\s*(?:=|;|\[)')


def _close(text, start, left='(', right=')'):
    """The index of the bracket that closes the one at `start` (pattern_repairs.close gives the index after it)."""
    after = close(text, start, left, right)
    return after - 1 if after else None


def _python_enclosing_close(clean, pos, lo, hi):
    """The `}` that closes the innermost block holding `pos` (within lo..hi), or None."""
    depth = 0
    i = pos
    while i < hi:
        c = clean[i]
        if c == '{':
            depth += 1
        elif c == '}':
            if depth == 0:
                return i
            depth -= 1
        i += 1
    return None


_enclosing_close = _python_enclosing_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _enclosing_close(clean, pos, lo, hi):
        found = _scan.enclosing_end(clean, pos, hi, None)
        return _python_enclosing_close(clean, pos, lo, hi) if found is NotImplemented else found


def _negate(cond):
    """`!(cond)`, and the flipped comparison when `cond` is one `(...) != 0` / `== 0` test."""
    out = ['!(' + cond + ')']
    m = re.fullmatch(r'(?s)(.*\S)\s*(!=|==)\s*(0|NULL)', cond)
    if m:
        left = m[1]
        if left.startswith('(') and _close(left, 0) == len(left) - 1 or re.fullmatch(r'[\w.\->\[\]]+', left):
            out.insert(0, f"{left} {'==' if m[2] == '!=' else '!='} {m[3]}")
    return out


def _sites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = _close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    out = []
    for m in re.finditer(r'\bif\s*\(', clean[opening:end]):
        start = opening + m.start()
        paren = opening + m.end() - 1
        cond_end = _close(clean, paren)
        if not cond_end:
            continue
        brace = cond_end + 1
        while brace < end and clean[brace].isspace():
            brace += 1
        if brace >= end or clean[brace] != '{':
            continue
        arm_end = _close(clean, brace, '{', '}')
        if not arm_end:
            continue
        arm = clean[brace + 1:arm_end]
        jump = re.search(rf'goto\s+({IDENT})\s*;\s*$', arm)
        if not jump or re.search(r'\bgoto\b', arm[:jump.start()]):
            continue
        after = clean[arm_end + 1:]
        if re.match(r'\s*else\b', after):
            continue
        label = jump[1]
        if len(re.findall(rf'\bgoto\s+{label}\s*;', clean[opening:end])) != 1:
            continue
        outer_end = _enclosing_close(clean, arm_end + 1, arm_end + 1, end)
        if outer_end is None:
            continue
        where = [x for x in re.finditer(rf'(?<![\w.>])({label})\s*:(?!:)', clean[arm_end + 1:outer_end])]
        if len(where) != 1:
            continue
        at = arm_end + 1 + where[0].start()
        run_start = arm_end + 1 + where[0].end()
        run_end = _enclosing_close(clean, run_start, run_start, outer_end + 1)
        if run_end is None:
            continue
        run = clean[run_start:run_end]
        if not run.strip() or _BAD_RUN.search(run) or _DECL.search(run) or '{' in run:
            continue
        if clean[run_end:outer_end].strip('} \t\r\n'):
            continue
        out.append({'start': start, 'cond': source[paren + 1:cond_end], 'brace': brace, 'arm_end': arm_end,
                    'jump': brace + 1 + jump.start(), 'label_at': at, 'run_start': run_start, 'run_end': run_end,
                    'outer_end': outer_end})
    return out


def _indent(source, pos):
    line = source.rfind('\n', 0, pos) + 1
    return re.match(r'[ \t]*', source[line:])[0]


def _rewrite(source, site, negated):
    """Edits (start, stop, text) for one site."""
    s = site
    indent = _indent(source, s['start'])
    x = source[s['brace'] + 1:s['jump']].rstrip()
    run = source[s['run_start']:s['run_end']].strip()
    rest = source[s['arm_end'] + 1:s['outer_end']]
    off = s['arm_end'] + 1
    label_line = source.rfind('\n', 0, s['label_at']) + 1
    label_stop = s['run_start']
    if not source[label_line:s['label_at']].strip():
        rest = rest[:label_line - off] + rest[label_stop - off:].lstrip(' \t')
        if rest[label_line - off:label_line - off + 1] == '\n':
            rest = rest[:label_line - off] + rest[label_line - off + 1:]
    else:
        rest = rest[:s['label_at'] - off] + rest[label_stop - off:]
    body = rest.rstrip()
    tail = source[len(source[:s['outer_end']].rstrip()):s['outer_end']]
    text = (f"if ({negated})\n{indent}{{{body}\n{indent}}}\n{indent}else\n{indent}{{{x}\n"
            f"{indent}  {run}\n{indent}}}")
    return (s['start'], s['outer_end'], text + tail)


def _apply(source, edits):
    for start, stop, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[stop:]
    return source


def variants(source, name):
    sites = _sites(source, name)
    # nested sites overlap: keep the ones that don't contain another
    sites = [s for s in sites
             if not any(o is not s and s['start'] < o['start'] and o['outer_end'] <= s['outer_end'] for o in sites)
             and not any(o is not s and o['start'] < s['start'] < o['outer_end'] for o in sites)]
    out = []
    for site in sites:
        for negated in _negate(site['cond']):
            out.append((FAMILY, _apply(source, [_rewrite(source, site, negated)])))
    if len(sites) > 1:
        out.insert(0, (FAMILY, _apply(source, [_rewrite(source, s, _negate(s['cond'])[0]) for s in sites])))
    seen, unique = set(), []
    for family, text in out:
        if text not in seen and text != source:
            seen.add(text)
            unique.append((family, text))
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}  # the registry: no caller wiring (registry.py)
