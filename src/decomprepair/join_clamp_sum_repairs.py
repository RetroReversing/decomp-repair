"""Three source shapes that closed a 319-instruction KMC gcc 2.7.2 menu function (410 -> 0), each a step the
permuter had no rewrite for. Hypotheses about the compiler are labelled as such; the judge decides every child.

plus_one_clamp_compare
    m2c writes an unsigned-byte clamp as `if ((v + 1) < (0xFFU + 1))`. The target compares the byte itself
    (`sltiu $v0, $v1, 0xff`), with no `addiu $v0, $v1, 1` before it. For a local declared `u8`/`u16` (so `v + 1`
    cannot wrap) the two tests are equal, and the rewrite is `if (v < 0xFF)`.

copy_across_join
    A pointer `P` checked non-null, then stored through after a branch diamond (a float-to-unsigned conversion). The
    target keeps a *copy* `move $a0, $v1` made before the diamond and stores through the copy. Hypothesis (cse.c,
    `cse_end_of_basic_block`): the copy is only an equal of `P` inside the extended block that holds it; a label with
    two uses ends the block, so a use after the diamond reads the copy's own register. Written next to the store the
    copy is folded into `P` and vanishes. The rewrite puts `Q = P;` early (right after the null check) and reads `Q`
    at the first use after a closed `if`, where `Q` is another pointer local of the same type that the function sets
    elsewhere.

wide_sum_temp
    `*(s16 *)x = (s16) (a + b);` is narrowed to a halfword addition by the front end (convert_to_integer, MIPS
    TRULY_NOOP_TRUNCATION), and `expand_binop` then swaps a register second operand in front of a SUBREG first one:
    `addu $v0, $v0, $v1` where the target has `addu $v0, $v1, $v0`. Hypothesis: written as a full-width sum in a
    local, `s32 sum = a + b; *(s16 *)x = (s16) sum;`, the addition keeps its operand order and the store takes the low
    half. One new `s32` local; no instruction is added or removed.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .pattern_repairs import close

FAMILY_CLAMP = 'plus_one_clamp_compare'
FAMILY_COPY = 'copy_across_join'
FAMILY_SUM = 'wide_sum_temp'
FAMILIES = (FAMILY_CLAMP, FAMILY_COPY, FAMILY_SUM)
LIMIT = 6
_NARROW = {'u8': 8, 'unsigned char': 8, 'u16': 16, 'unsigned short': 16}

_CLAMP = re.compile(rf'\(\s*(?P<var>{IDENT})\s*\+\s*1\s*\)\s*<\s*\(\s*(?P<limit>{NUMBER})\s*\+\s*1\s*\)')


def _clamp(source, name):
    part = view(source, name)
    if not part:
        return []
    result = []
    for hit in _CLAMP.finditer(part.clean, part.opening + 1, part.end):
        declared = re.search(rf'\b(?P<type>u8|u16|unsigned\s+char|unsigned\s+short)\s+{hit["var"]}\s*;', part.clean)
        if not declared:
            continue
        bits = _NARROW[re.sub(r'\s+', ' ', declared['type'])]
        if integer(hit['limit']) + 1 > 1 << bits:
            continue
        number = source[hit.start('limit'):hit.end('limit')]
        result.append((FAMILY_CLAMP, edit(source, [(hit.start(), hit.end(), f'{hit["var"]} < {number}')])))
    return result[:LIMIT]


_POINTER_DECL = re.compile(rf'(?m)^[ \t]*(?P<type>(?:struct\s+)?{IDENT})[ \t]*(?:volatile[ \t]*)?\*[ \t]*(?P<name>{IDENT})[ \t]*;')


def _copy(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pointers = {}
    for decl in _POINTER_DECL.finditer(clean, part.opening + 1, part.end):
        pointers.setdefault(re.sub(r'\s+', ' ', decl['type']), []).append(decl['name'])
    result = []
    for kind, names in pointers.items():
        for origin in names:
            set_origin = re.compile(rf'(?m)^[ \t]*{origin}[ \t]*=[^=;][^;]*;[ \t]*\n[ \t]*if[ \t]*\([ \t]*{origin}[ \t]*(?:!=[ \t]*NULL[ \t]*)?\)[ \t]*\n?[ \t]*\{{[ \t]*\n')
            for guard in set_origin.finditer(clean, part.opening + 1, part.end):
                block_open = clean.rindex('{', guard.start(), guard.end())
                block_close = close(clean, block_open, '{', '}')
                if not block_close:
                    continue
                inside = clean[guard.end():block_close - 1]
                # The first use of the origin after a nested `if` has closed: a join stands between.
                nested = re.search(r'\bif\b[^;{}]*\)[ \t]*\n?[ \t]*\{', inside)
                if not nested:
                    continue
                nested_open = guard.end() + nested.end() - 1
                nested_close = close(clean, nested_open, '{', '}')
                if not nested_close:
                    continue
                tail = nested_close
                while True:
                    follow = re.match(r'\s*else\b[^{;]*\{', clean[tail:block_close])
                    if not follow:
                        break
                    after = close(clean, tail + follow.end() - 1, '{', '}')
                    if not after:
                        break
                    tail = after
                use = re.compile(rf'(?<![\w.>]){origin}\b').search(clean, tail, block_close)
                if not use or re.match(r'\s*(?:=[^=]|\+\+|--)', clean[use.end():]):
                    continue
                for copy in names:
                    if copy == origin:
                        continue
                    sets = re.findall(rf'(?m)(?<![\w.>]){copy}[ \t]*=[^=]', clean[part.opening + 1:part.end])
                    mentioned = re.search(rf'\b{copy}\b', clean[guard.end():use.start()])
                    if not sets or mentioned:
                        continue
                    indent = re.match(r'[ \t]*', clean[guard.end():])[0]
                    result.append((FAMILY_COPY, edit(source, [(guard.end(), guard.end(), f'{indent}{copy} = {origin};\n'),
                                                              (use.start(), use.end(), copy)])))
    return result[:LIMIT]


_STORE = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>[^;=\n]*\*[^;=\n]+?)[ \t]*=[ \t]*\((?P<type>s16|u16|s8|u8)\)[ \t]*\((?P<sum>[^;]+)\)[ \t]*;[ \t]*$')


def _python_top_level_plus(text):
    depth, found = 0, []
    for pos, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if depth == 0 and char == '+' and text[pos - 1:pos + 2] == ' + ':
            found.append(pos)
    return found


_top_level_plus = _python_top_level_plus
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _top_level_plus(text):
        return [at for at in _scan.top_offsets(text, '+', 2) if text[at - 1:at + 2] == ' + ']


def _sum(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for hit in _STORE.finditer(clean, part.opening + 1, part.end):
        sum_text = hit['sum']
        if len(_top_level_plus(sum_text)) != 1 or '++' in sum_text or '--' in sum_text:
            continue
        # Plain loads, locals and casts only: a call in the sum would be reordered by nothing here.
        if re.search(rf'\b(?!s8|u8|s16|u16|s32|u32|f32|void|char|short|int|volatile|M2C_FIELD|sizeof)({IDENT})\s*\(', sum_text):
            continue
        temp = 'wide_sum'
        suffix = 2
        while re.search(rf'\b{temp}\b', clean[part.opening:part.end]):
            temp, suffix = f'wide_sum_{suffix}', suffix + 1
        indent = hit['indent']
        statement = f'{indent}{temp} = {source[hit.start("sum"):hit.end("sum")]};\n{indent}{source[hit.start("lhs"):hit.end("lhs")]} = ({hit["type"]}) {temp};'
        top = part.opening + 1
        result.append((FAMILY_SUM, edit(source, [(top, top, f'\n  s32 {temp};'), (hit.start(), hit.end(), statement)])))
    return result[:LIMIT]


def variants(source, name):
    return _clamp(source, name) + _copy(source, name) + _sum(source, name)
