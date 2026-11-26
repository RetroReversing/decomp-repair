"""Two adjacent word stores of the same constant at offsets K and K + 4 (K a multiple of 8): one `s64` store.

Observed (GCC 2.7.2 SN/KMC `-G0 -mips3 -mgp32 -O2`; one 25-instruction function that clears a pair of words next to
a list head, 210 -> 20): m2c writes the two halves of a cleared doubleword as two word stores,

    M2C_FIELD(D_800BD2B8, s32 *, 0) = 0;
    M2C_FIELD(D_800BD2B8, s32 *, 4) = 0;           /* draft: `sw $zero, 0($a0)`, `sw $zero, 4($a0)` */
    *(s64 *)D_800BD2B8 = 0;                        /* target: `move $v0,$zero`, `move $v1,$zero`, `sw $v0`, `sw $v1` */

and the game's source stored a 64-bit zero: the compiler keeps the doubleword in a register pair, materializes both
halves with `move` and splits the store into two `sw` of those registers at reload, where two word stores use
`$zero` directly. The two rows of `move` and the two stores' registers are what the draft is missing (210 -> 20; the
last four rows are the pair's registers, `$a2/$a3` where the target has `$v0/$v1`: variants with a `u64`, a local
`s64`, an `s64` array and a `long long` cast measured the same 20, so this family stops there).

Children, for two statements written back to back that store the same constant (zero, or 1 to 0x7FFFFFFF) through the
same plain base (a name or a member chain) at K and K + 4, K a multiple of 8, as `M2C_FIELD(b, T *, K)`, `*(T *)(b + K)`,
`*(T *)b` or `((T *)b)[i]` (i even), `T` a 32-bit integer type: one `s64` store of the combined value (the constant in
both halves; big-endian words, the same either way for equal halves). When the target's assembly is given it must
store two different registers other than `$zero` to offsets 4 apart off one base, the doubleword's split halves (a
target that keeps `sw $zero` twice was not written this way). Only MIPS. Proposals only; the judge decides."""
import re

FAMILIES = ('word_pair_doubleword_store',)
FAMILY = FAMILIES[0]
LIMIT = 6
_BASE = r'[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)*'
_WORD = r'(?:s32|u32|M2C_UNK|M2C_UNK32|int|unsigned int|unsigned)'
_NUM = r'0[xX][0-9A-Fa-f]+|\d+'
_CONST = r'(?:' + _NUM + r')'
_ATOMS = (
    ('field', re.compile(r'M2C_FIELD\(\s*(?P<b>' + _BASE + r')\s*,\s*' + _WORD + r'\s*\*\s*,\s*(?P<o>' + _NUM + r')\s*\)\s*=\s*(?P<c>' + _CONST + r')\s*;')),
    ('plus', re.compile(r'\*\s*\(\s*' + _WORD + r'\s*\*\s*\)\s*\(\s*(?P<b>' + _BASE + r')\s*\+\s*(?P<o>' + _NUM + r')\s*\)\s*=\s*(?P<c>' + _CONST + r')\s*;')),
    ('deref', re.compile(r'\*\s*\(\s*' + _WORD + r'\s*\*\s*\)\s*(?P<b>' + _BASE + r')\s*=\s*(?P<c>' + _CONST + r')\s*;')),
    ('index', re.compile(r'\(\s*\(\s*' + _WORD + r'\s*\*\s*\)\s*(?P<b>' + _BASE + r')\s*\)\s*\[\s*(?P<i>' + _NUM + r')\s*\]\s*=\s*(?P<c>' + _CONST + r')\s*;')),
)
_STORE = re.compile(r'\bsw\s+\$(\w+)\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))?\(\s*\$(\w+)\s*\)')


def _mask(source):
    def blank(m):
        return re.sub(r'[^\n]', ' ', m[0])
    text = re.sub(r'/\*.*?\*/|//[^\n]*', blank, source, flags=re.S)
    return re.sub(r'(?m)^[ \t]*#(?:[^\n\\]|\\\n)*', blank, text)


def _atoms(text):
    """[(start, end, kind, base, byte offset, constant)] of every word store of a literal, in source order."""
    found = []
    for kind, pattern in _ATOMS:
        for m in pattern.finditer(text):
            if kind == 'deref':
                offset = 0
            elif kind == 'index':
                offset = int(m['i'], 0) * 4
            else:
                offset = int(m['o'], 0)
            found.append((m.start(), m.end(), kind, m['b'], offset, int(m['c'], 0)))
    return sorted(found)


def _split_pair(asm):
    """True when the assembly stores two different non-zero registers 4 bytes apart off one base register."""
    seen = {}
    for reg, off, base in _STORE.findall(asm):
        if reg not in ('zero', '0'):
            seen.setdefault(base, []).append((int(off, 0) if off else 0, reg))
    for rows in seen.values():
        for a, ra in rows:
            if any(b == a + 4 and rb != ra for b, rb in rows):
                return True
    return False


def _store(base, offset, constant):
    value = '0' if constant == 0 else f'0x{constant:08X}{constant:08X}'
    if offset:
        return f'M2C_FIELD({base}, s64 *, {offset}) = {value};'
    return f'*(s64 *){base} = {value};'


def variants(source, name=None, asm=None):
    if asm and not _split_pair(asm):
        return []
    text = _mask(source)
    atoms = _atoms(text)
    sites = []
    for first in atoms:
        start, end, kind, base, offset, constant = first
        if offset % 8 or not 0 <= constant <= 0x7FFFFFFF:
            continue
        for second in atoms:
            if (second[0] < end or second[3] != base or second[4] != offset + 4
                    or second[5] != constant or text[end:second[0]].strip()):
                continue
            sites.append((start, second[1], _store(base, offset, constant)))
    if not sites:
        return []

    def apply(chosen):
        out = source
        for a, b, spelled in sorted(chosen, reverse=True):
            out = out[:a] + spelled + out[b:]
        return out
    kids = [apply([s]) for s in sites]
    if len(sites) > 1:
        kids.append(apply(sites))
    return [(FAMILY, k) for k in dict.fromkeys(kids) if k != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
