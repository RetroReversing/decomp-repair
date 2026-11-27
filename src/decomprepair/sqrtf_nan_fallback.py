"""m2c's inline square root with its NaN retry: `v = sqrtf(a); if (v != v) { v = fallback(a); }` is the compiler's own `sqrtf`.

GCC 2.8 (the SN and KMC N64 builds, `-mfp32` or not) expands `sqrtf(x)` to `sqrt.s`, a `c.eq.s v, v` self-compare and, for a
NaN, a call of the C library's `sqrtf` (to set errno). m2c reads those bytes as the source it would need to produce them:

    temp_fa0 = x*x + y*y + z*z;
    temp_fv0 = sqrtf(temp_fa0);
    if (temp_fv0 != temp_fv0) { func_80094350(temp_fa0); }       /* func_80094350 is the library's sqrtf */

and a source that spells the retry out compiles the check twice (the builtin's and its own). The game wrote only
`sqrtf(a)`: dropping the `if` block is the match (a vector length, `f32 f(Vec3 *v) { return sqrtf(v->x*v->x + ...); }`,
and the same hunk in about a quarter of the open functions of an N64 game that does vector maths).

The double root is the same (`sqrt.d`, `c.eq.d`, a call of `sqrt` for a NaN): m2c writes `v = sqrt(a); if (v != v) { v =
fallback(); }`, and only `sqrt(a)` was written (`f64 sqrt(f64);` declared). With
`double_unsigned_conversion` an SN64 GCC 2.8.1 fixed-point square root's m2c draft reaches the match.

The evidence is the target's own assembly: a `sqrt.s` (or `sqrt.d`), and a `jal` of the callee the retry block calls. The shape: an
`if (X != X) { [Y =] callee(args); }` after an `X = sqrtf(...)` (X assigned from sqrtf earlier in the function), Y being X
or a variable set from X (`var_fs0 = temp_fv0;` before the check). Children:
- `sqrtf_nan_fallback`: every retry block removed (and `f32 sqrtf(f32);` declared when the source and the header have no
  declaration, so the call is not an implicit-int one);
- `sqrtf_nan_fallback_one`: one block removed, for a function with several (at most six children), because the target's
  other roots may differ;
- `sqrtf_nan_fallback_return`: a `void` function whose last statement is the check, with `$f0` still holding the root in
  the target's epilogue (no later write to `$fv0`): declared `f32` and returning the root, which is how the target's
  caller reads it (`return sqrtf(...)` was the form that matched).
The judge decides; the rewrite is gated on `sqrt.s` and the retry call both being in the target, so it never fires on a
function that did not use the builtin."""
import re

from .arm_block_support import IDENT, brace_pairs
from .integer_repair_support import edit, view
from .void_parameter_return import _rows

FAMILY = 'sqrtf_nan_fallback'
FAMILIES = (FAMILY, FAMILY + '_one', FAMILY + '_return')

CHECK = re.compile(rf'(?m)^(?P<lead>[ \t]*)if\s*\(\s*(?P<var>{IDENT})\s*!=\s*(?P=var)\s*\)\s*\{{')
ROOT = re.compile(rf'\b(?P<var>{IDENT})\s*=\s*(?P<root>sqrtf?)\s*\(')
# the root as C calls it: the instruction it compiles to, its value's type
KINDS = {'sqrtf': ('sqrt.s', 'f32'), 'sqrt': ('sqrt.d', 'f64')}
RETRY = re.compile(rf'\s*(?:(?P<set>{IDENT})\s*=\s*)?(?P<callee>{IDENT})\s*\([^;{{}}]*\)\s*;\s*')
MAX_ONE = 6


def evidence(asm):
    """The functions the target calls, when it holds a `sqrt.s` or `sqrt.d`; None when it holds neither."""
    rows = _rows(asm)
    if not any(op in ('sqrt.s', 'sqrt.d') for op, _ in rows):
        return None
    return {args.split()[0].strip() for op, args in rows if op == 'jal' and args}


def _live_root(asm):
    """Whether `$fv0` (the return register) is not written after the last root apart from the retry call."""
    rows = _rows(asm)
    roots = [i for i, (op, args) in enumerate(rows) if op in ('sqrt.s', 'sqrt.d')]
    if not roots or not re.match(r'\$(?:fv0|f0)\b', rows[roots[-1]][1]):
        return False
    for op, args in rows[roots[-1] + 1:]:
        if op in ('jal', 'jalr', 'jr', 'nop', 'label') or op.startswith(('b', 'c.')):
            continue
        if re.match(r'\$(?:fv0|f0)\b', args):
            return False
    return True


def _sites(part, called, roots):
    """[(start, end, checked variable, root function)] of the retry blocks: the line start to just past the closing brace."""
    clean, found = part.clean, []
    pairs = brace_pairs(clean, part.opening, part.end)
    if pairs is None:
        return []
    for hit in CHECK.finditer(clean, part.opening, part.end):
        opening = hit.end() - 1
        closing = pairs.get(opening)
        if closing is None:
            continue
        retry = RETRY.fullmatch(clean[opening + 1:closing])
        if not retry or retry['callee'] not in called:
            continue
        rooted = [m for m in ROOT.finditer(clean, part.opening, hit.start()) if m['var'] == hit['var']]
        if not rooted or rooted[-1]['root'] not in roots:
            continue
        if retry['set'] and retry['set'] != hit['var'] and not re.search(
                rf'\b{re.escape(retry["set"])}\s*=\s*{re.escape(hit["var"])}\s*;', clean[part.opening:hit.start()]):
            continue
        found.append((hit.start(), closing + 1, hit['var'], rooted[-1]['root']))
    return found


def _cut(source, spans):
    edits = []
    for start, end, *_ in spans:
        tail = end
        while tail < len(source) and source[tail] in ' \t':
            tail += 1
        if tail < len(source) and source[tail] == '\n':
            tail += 1
        edits.append((start, tail, ''))
    return edits


def _declared(source, header, root):
    kind = 'f32|float' if root == 'sqrtf' else 'f64|double'
    return re.search(rf'(?m)^[ \t]*(?:extern[ \t]+)?(?:{kind})[ \t]+{root}[ \t]*\(', source + '\n' + (header or '')) is not None


def _prototype(source, header, at, sites):
    text = ''.join(f'{KINDS[root][1]} {root}({KINDS[root][1]});\n' for root in sorted({s[3] for s in sites})
                   if not _declared(source, header, root))
    return [(at, at, text)] if text else []


def variants(source, name, asm, header=''):
    called = evidence(asm)
    part = view(source, name) if called is not None else None
    if not part:
        return []
    ops = {op for op, _ in _rows(asm)}
    sites = _sites(part, called, {root for root, (op, _) in KINDS.items() if op in ops})
    if not sites:
        return []
    from .csource import find
    top = find(source, name)[0]
    top = source.rfind('\n', 0, top) + 1
    proto = _prototype(source, header, top, sites)
    out = [(FAMILY, edit(source, _cut(source, sites) + proto))]
    if len(sites) > 1:
        for site in sites[:MAX_ONE]:
            out.append((FAMILY + '_one', edit(source, _cut(source, [site]) + proto)))
    last = sites[-1]
    signature = re.search(rf'(?P<head>[^;{{}}]*?)\b{re.escape(name)}\s*\([^()]*\)\s*$', part.clean[top:part.opening])
    tail = part.clean[last[1]:part.end].strip()
    if signature and tail == '}' and re.search(r'\bvoid\s*$', signature['head']) and _live_root(asm):
        at = top + signature.start('head')
        edits = _cut(source, sites) + proto
        spelled = signature['head']
        void = spelled.rindex('void')
        edits.append((at + void, at + void + 4, KINDS[last[3]][1]))
        close = part.clean.rfind('}', 0, part.end)
        edits.append((close, close, f'    return {last[2]};\n'))
        out.append((FAMILY + '_return', edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'),
          'order': 62, 'archs': ('mips',)}
