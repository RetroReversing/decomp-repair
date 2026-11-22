"""Loop-depth weight for a guarded copy block, and a quotient with a staged sum in one scope that also holds the test.

GCC 2.x counts a pseudo's references once per enclosing loop (flow.c adds `loop_depth` to `reg_n_refs`), and a
`do { } while (0)` is a loop to flow.c while costing no instruction. Two register-only near-misses in a KMC GCC 2.7.2
N64 voice-allocation function (`-G0 -mips3 -mgp32 -mfp32 -O2`, 217 instructions) were decided by those weights; neither
shape was produced by any family (322 children of the saved best, none better than 85):

- `guarded_body_scope`: the straight-line body of an `if` (stores and copies, no call or jump) wrapped in a one-shot
  scope. Each reference inside counts twice, so the variable the block stores and reassigns outranks a neighbour in
  global.c's `floor_log2(refs) * refs / live length` (14 references against 13 over a similar live range: `$s2`/`$s3`
  came out right, 85 -> 25).
- `staged_sum_scope`: a quotient statement followed by m2c's split sum (`v = load; v = x + v;`) and `if (v < K)`.
  Rewritten as `b = load_q; do { q = (a * b) / N; v = x; v += load; flag = v < K; } while (0); if (flag)`:
  - `v = x; v += load;` makes the masked value the sum's first operand and, `v` being live across blocks (global), keeps
    local-alloc from tying the shift to the mask (combine_regs refuses a set register without a local quantity);
  - the scope doubles the shift's and the product's references, so in local-alloc's `qty_compare_1` the two-insn shift
    (4 references over 2) outranks the product (16 over ~22) and takes `$v0`, the product `$v1`, as the target has;
  - the factor's load stays outside so the walking pointer gains only one reference (its global priority stays below
    its neighbour's);
  - the test inside the scope: sched.c makes the insn after a loop note depend on everything before it, so with the
    scope closing before `slt` the comparison was pinned last, behind the quotient's `mfhi` (one `nop` short).
  Children also wrap one earlier load-and-add assignment, which compensates the extra parameter reference the scope
  adds (the saved registers of the target kept the parameter spilled). From 25: 0 with the earlier statement wrapped,
  1657 without; each of the four edits alone was worse (970, 2562, ...).

The priority readings come from `-dl -dg` dumps and local-alloc.c/global.c/sched.c of the 2.7.2 source; the sched.c
loop-note rule is in the source, the rest is measured on one function (hypotheses beyond it). The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

GUARDED = 'guarded_body_scope'
STAGED = 'staged_sum_scope'
FAMILIES = (GUARDED, STAGED)
LIMIT = 8
EARLIER = 3
_JUMP = re.compile(r'\b(?:return|goto|break|continue|if|else|for|while|do|switch|case|asm|__asm__)\b')
_CALL = re.compile(rf'\b{IDENT}\s*\(\s*(?!\s*(?:\w+\s*)+\**\s*\))')
_SCALAR = r'(?:unsigned\s+|signed\s+)?(?:char|short|int|long|[su](?:8|16|32))'


def _close(text, start):
    """Index after the parenthesis that closes the one at `start`, or -1."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _plain(statement):
    """A straight-line statement: no call, jump, block or conditional."""
    return not (_JUMP.search(statement) or _CALL.search(statement) or re.search(r'[{}?]', statement))


def _guarded(source, part):
    out = []
    clean = part.clean
    for hit in re.finditer(r'\bif\s*\(', clean[part.opening:part.end]):
        start = part.opening + hit.end() - 1
        after = _close(clean, start)
        if after < 0:
            continue
        brace = re.match(r'\s*\{', clean[after:])
        if not brace:
            continue
        body_start = after + brace.end()
        depth, i = 1, body_start
        while i < part.end and depth:
            depth += {'{': 1, '}': -1}.get(clean[i], 0)
            i += 1
        body = clean[body_start:i - 1]
        statements = [s for s in body.split(';')[:-1]]
        if len(statements) < 2 or not body.strip().endswith(';') or not all(_plain(s) and '=' in s for s in statements):
            continue
        text = source[body_start:i - 1]
        out.append((GUARDED, edit(source, [(body_start, i - 1, '\ndo {' + text.rstrip() + '\n} while (0);\n')])))
    return out


def _load(text):
    """The first `(*((T *) (...)))` read in `text`: (start, end, type)."""
    for hit in re.finditer(rf'\(\s*\*\s*\(\s*\(\s*(?P<t>{_SCALAR})\s*\*\s*\)', text):
        end = _close(text, hit.start())
        if end > 0:
            return hit.start(), end, hit['t']
    return None


def _declare(source, part, name, ctype):
    """Edit that declares `ctype name;` after the function's opening brace."""
    return (part.opening + 1, part.opening + 1, f'\n  {ctype} {name};')


def _fresh(part, stem):
    name, n = stem, 0
    while re.search(rf'\b{name}\b', part.clean):
        n += 1
        name = f'{stem}{n}'
    return name


def _staged(source, part):
    clean = part.clean
    pattern = re.compile(
        rf'(?<=[;{{}}])(?P<quot>\s*(?P<q>{IDENT})\s*=\s*[^;{{}}]*/\s*[0-9]+[uU]?\s*;)'
        rf'(?P<split>\s*(?P<v>{IDENT})\s*=\s*(?P<load>[^;{{}}]+?)\s*;\s*(?P=v)\s*=\s*(?P<x>[^;{{}}]+?)\s*\+\s*(?P=v)\s*;)'
        rf'(?P<test>\s*if\s*\(\s*(?P=v)\s*(?P<op><=|>=|<|>)\s*(?P<k>(?:0x[0-9A-Fa-f]+|[0-9]+)[uU]?)\s*\))')
    out = []
    for hit in pattern.finditer(clean, part.opening, part.end):
        if not _plain(hit['quot']) or not _plain(hit['split']):
            continue
        q_text = source[hit.start('quot'):hit.end('quot')].strip()
        load = _load(q_text)
        flag = _fresh(part, 'in_range')
        v, x, src_load = hit['v'], source[hit.start('x'):hit.end('x')].strip(), source[hit.start('load'):hit.end('load')].strip()
        test = f'{v} {hit["op"]} {hit["k"]}'
        heads = []
        if load:
            factor = _fresh(part, 'factor')
            ls, le, ltype = load
            heads.append((f'{factor} = {q_text[ls:le]};\n', q_text[:ls] + factor + q_text[le:], (factor, ltype)))
        heads.append(('', q_text, None))
        earlier = []
        for prior in re.finditer(rf'(?<=[;{{}}])(?P<s>\s*{IDENT}\s*=\s*{IDENT}\s*\+\s*[^;{{}}]*;)', clean[part.opening:hit.start()]):
            s = prior['s']
            if _plain(s) and _load(s) and re.search(r'\+', s):
                earlier.append((part.opening + prior.start('s'), part.opening + prior.end('s')))
        earlier = earlier[-EARLIER:][::-1]
        for pre, quotient, factor in heads:
            block = (f'\n{pre}do {{\n{quotient}\n{v} = {x};\n{v} += {src_load};\n{flag} = {test};\n}} while (0);\n'
                     f'if ({flag})')
            base = [(hit.start('quot'), hit.end('test'), block), _declare(source, part, flag, 's32')]
            if factor:
                base.append(_declare(source, part, factor[0], factor[1]))
            for s, e in earlier:
                wrapped = 'do {' + source[s:e].rstrip() + '\n} while (0);'
                out.append((STAGED, edit(source, base + [(s, e, wrapped)])))
            out.append((STAGED, edit(source, base)))
    return out


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp|volatile)\b|^\s*#', part.body, re.M):
        return []
    return (_staged(source, part) + _guarded(source, part))[:LIMIT * 2]
