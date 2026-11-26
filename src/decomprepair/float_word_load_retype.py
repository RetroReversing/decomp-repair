"""A word read into a float local as an integer (and so converted), where the target loads it straight into an FP register.

m2c types a load by how the value is used and sometimes picks the integer view of a word that the game only copies
through the FPU:

    f32 t;                                   f32 t;
    t = *(s32 *)(base + off);        ->      t = *(f32 *)(base + off);        (`lwc1`, no conversion)
    *dst = t;                                *dst = t;

The integer read assigned to a float local is a `lw` and a `cvt.s.w`, the float read is the target's single `lwc1`.
A matrix-copy loop (KMC GCC 2.7.2, `-O2 -G0 -mips3 -mgp32 -mfp32`) sat at 100 with the integer read and was exact with
`f32` in its place. `unknown32_float` covers `M2C_UNK32` fields; this covers a read written with an explicit word
type: `*(s32 *)(addr)`, `*(u32 *)(addr)`, `M2C_FIELD(x, s32 *, off)`, with or without an explicit `(f32)` cast on it.

The same read multiplied or divided inside an expression (`(a - b) * *(s32 *)(table + i * 4)`, a float table m2c typed
as words) converts too. A 60-instruction N64 float state update (KMC GCC 2.7.2 `-O1 -G0 -mips3 -mgp32 -mfp32`): the
m2c draft was 390 with the word read, 140 with `f32`, and `store_tail_into_arms` matched from there. Offered for a
`*(word *)` operand of `*` or `/` only (a `+` there may be address arithmetic), and with `asm` only when the target
converts no integer to float at all.

Offered for a statement `local = READ;` (or `local = (f32) READ;`) whose local is a plain `f32`/`float` local of the
function. Evidence from `asm` when given: the target has an `lwc1` and fewer `cvt.s.w` than the source has such
conversions (otherwise the conversion is the game's and nothing is offered). One child per site and one with every site.
A hypothesis like every other family's: the judge decides.
"""
import re

from .case_temporary_repairs import DECLARATION
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'float_word_load_retype'
FAMILIES = (FAMILY,)
LIMIT = 8
WORD = r'(?:s32|u32|int|unsigned int|unsigned|M2C_UNK32)'
READ = (r'(?:\*\s*\(\s*(?P<ptr>' + WORD + r')\s*\*\s*\)[^;]*?|'
        r'M2C_FIELD\s*\([^;]*?,\s*(?P<fptr>' + WORD + r')\s*\*\s*,[^;]*?\))')
SITE = re.compile(r'(?m)(?:^|(?<=[;{}]))(?P<lead>\s*)(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<cast>\(\s*(?:f32|float)\s*\)\s*)?'
                  + READ + r'\s*;')


OPERAND = re.compile(r'\*\s*\(\s*(?:\(\s*)?(?P<ptr>' + WORD + r')\s*\*\s*\)')
LONE_CAST = re.compile(r'\(\s*' + WORD + r'\s*\*\s*\)$')


def _read_end(clean, star):
    """Just past the dereference that starts at the `*` at `star`: `*(T *)x`, `*(T *)(..)` or `*((T *) ..)`."""
    opening = clean.index('(', star)
    after = close(clean, opening)
    if not after or not LONE_CAST.match(clean[opening:after]):
        return after
    rest = re.compile(r'\s*([A-Za-z_]\w*)?').match(clean, after)
    following = re.compile(r'\s*\(').match(clean, after)
    if following:
        return close(clean, following.end() - 1)
    return rest.end() if rest[1] else None


def _operands(clean, opening, end):
    """The word dereferences that are an operand of `*` or `/`."""
    out = []
    for m in OPERAND.finditer(clean, opening + 1, end):
        before = clean[:m.start()].rstrip().rstrip('( \t\n')
        if before[-1:] not in ('*', '/') or not re.search(r'[\w\])]\s*[*/]$', before):
            before = None
        stop = _read_end(clean, m.start())
        after = stop and clean[stop:end].lstrip(') \t\n')
        if before or (after and after[:1] in ('*', '/') and after[1:2] not in ('/', '*')
                      and re.search(r'[(=,*/+\-]\s*$', clean[:m.start()])):
            out.append(m)
    return out


def variants(source, name, asm=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    floats = {m['name'] for m in DECLARATION.finditer(clean, opening + 1, end)
              if re.sub(r'\b(?:register)\b', '', m['type']).strip() in ('f32', 'float')}
    sites = []
    for m in SITE.finditer(clean, opening + 1, end):
        if m['name'] not in floats:
            continue
        group = 'ptr' if m['ptr'] else 'fptr'
        sites.append((m, group))
    if asm:
        converted = len(re.findall(r'\bcvt\.s\.w\b', asm))
        if not re.search(r'\blwc1\b', asm):
            return []
        if converted >= len(sites):
            sites = []
    else:
        converted = 0
    assigned = {m.start(group) for m, group in sites}
    if not converted:
        sites += [(m, 'ptr') for m in _operands(clean, opening, end) if m.start('ptr') not in assigned]
    if not sites:
        return []

    def build(chosen):
        edits = []
        for m, group in chosen:
            edits.append((m.start(group), m.end(group), 'f32'))
            if m.groupdict().get('cast'):
                edits.append((m.start('cast'), m.end('cast'), ''))
        text = source
        for s, e, r in sorted(edits, reverse=True):
            text = text[:s] + r + text[e:]
        return text

    out = [(FAMILY, build([s])) for s in sites]
    if len(sites) > 1:
        out.append((FAMILY, build(sites)))
    return [(f, t) for f, t in out if t != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 45}
