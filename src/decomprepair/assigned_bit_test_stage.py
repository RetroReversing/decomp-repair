"""A stored single-bit test with the masked value staged in a local: `v = (x & 0x200) != 0;` -> `t = x & 0x200; v = t != 0;`.

GCC 2.x expands `(x & 2^n) != 0` used as a value by shifting the bit down (`srl; andi 1`, `do_store_flag`'s single-bit
path); a comparison of a plain variable with zero stays `andi; sltu`. Hypothesis from the matches, not confirmed in
the compiler source. A 511-instruction N64 input-sampling function (SN64 GCC 2.8.1, `-G0 -mips3 -O2`) unpacks 14
buttons of a halfword into `s32` flags; its target has fourteen `andi; sltu` pairs. Staging every test took a typed
candidate from 5920 to 1210 with one shared local, and with one local per test (and the other statement fixed by
`global_post_increment_split`) to 0.

`call_test_argument_stage` does the same for a test passed to a call; this is the assigned form, including m2c's
`(u32) (x & 4) > 0U` and a cast around the whole test.

assigned_bit_test_stage
    Every statement `V = (E & BIT) != 0;` (BIT one bit above bit 0; E without a call, assignment or `++`/`--`): all of
    them with one new local each, all with one shared local, then each site alone.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'assigned_bit_test_stage'
FAMILIES = (FAMILY,)
LIMIT = 10
PREFIX = 'bitTest'

_TYPE = r'(?:[su](?:8|16|32)|int|char|short|unsigned(?:\s+(?:int|char|short))?|signed\s+char)'
_LVALUE = rf'{IDENT}(?:(?:\.|->){IDENT}|\[[^][;=]*\])*'
_STATEMENT = re.compile(rf'(?<=[;{{}}])(?P<gap>\s*)(?P<dest>{_LVALUE})\s*=(?!=)\s*(?P<value>[^;{{}}=!<>]*&[^;{{}}]*);')
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uU]?'
_TESTS = (
    re.compile(rf'\((?P<word>.+?)\s*&\s*(?P<bit>{_NUMBER})\)\s*!=\s*0[uU]?', re.S),
    re.compile(rf'\(\s*u32\s*\)\s*\((?P<word>.+?)\s*&\s*(?P<bit>{_NUMBER})\)\s*>\s*0[uU]?', re.S),
)
_CAST = re.compile(rf'\(\s*{_TYPE}\s*\)\s*\((?P<inner>.*)\)', re.S)
_SIDE_EFFECT = re.compile(rf'\+\+|--|(?<![=!<>])=(?!=)|\b{IDENT}\s*\((?!\s*\*)')


def _balanced(text):
    depth = 0
    for bracket in re.findall(r'[()]', text):
        depth += 1 if bracket == '(' else -1
        if depth < 0:
            return False
    return depth == 0


def _test(value):
    """(cast prefix, word, bit) when the assigned value is a single-bit zero test, else None."""
    value, cast = value.strip(), ''
    wrapped = _CAST.fullmatch(value)
    if wrapped and _balanced(wrapped['inner']) and not wrapped['inner'].lstrip().startswith('u32'):
        cast = value[:value.index(')') + 1] + ' '
        value = wrapped['inner'].strip()
    for pattern in _TESTS:
        found = pattern.fullmatch(value)
        if not found:
            continue
        word, bit = found['word'].strip(), int(found['bit'].rstrip('uU'), 0)
        if bit < 2 or bit & (bit - 1) or not _balanced(word) or _SIDE_EFFECT.search(word):
            return None
        return cast, word, found['bit']
    return None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body) or PREFIX in source:
        return []
    sites = []
    for hit in _STATEMENT.finditer(part.clean, part.opening, part.end):
        test = _test(source[hit.start('value'):hit.end('value')])
        if test:
            sites.append((hit.start('dest'), hit.end(), source[hit.start('dest'):hit.end('dest')], test))
    if not sites:
        return []

    def build(chosen, shared):
        names, edits = [], []
        for number, (start, end, dest, (cast, word, bit)) in enumerate(chosen):
            local = PREFIX if shared else f'{PREFIX}{number}'
            if local not in names:
                names.append(local)
            line = source.rfind('\n', 0, start) + 1
            indent = source[line:start] if not source[line:start].strip() else ' '
            separator = '\n' + indent if indent != ' ' else ' '
            edits.append((start, end, f'{local} = {word} & {bit};{separator}{dest} = {cast}{"(" if cast else ""}'
                                      f'{local} != 0{")" if cast else ""};'))
        declarations = ''.join(f'\n    int {local};' for local in names)
        edits.append((part.opening + 1, part.opening + 1, declarations))
        return edit(source, edits)

    out = [build(sites, False)]
    if len(sites) > 1:
        out.append(build(sites, True))
        out.extend(build([site], False) for site in sites[:LIMIT - len(out)])
    return [(FAMILY, text) for text in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
