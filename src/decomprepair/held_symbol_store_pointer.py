"""Two stores around one symbol written through a pointer that holds its address, as the target does.

`D_80100020 = 0; D_8010000A = 0x10;` (or the second store as `*(s16 *)(&D_80100020 - 0x16)`) compiles to two absolute
stores through `$at`. The target keeps one address in a register and stores both through it
(`lui $v0; addiu $v0, $v0, %lo(D_80100020); sb $zero, 0($v0); sh $v1, -0x16($v0)`). A plain pointer local does not do
it: cse knows the pointer is the symbol and folds the offset back. A loop note ends the basic block cse works on, so the
pointer is assigned in a `do { } while (0)` and used after it. On an N64 game's menu input routine (KMC GCC 2.7.2
`-O1`) this took the plain switch from 1015 to 25, and `dead_pointer_address_reuse` then reached 0.

Offered only for a symbol the target materializes with `addiu rX, rY, %lo(SYM)` and stores through at offset 0 and at
another offset: the widths and that offset are read off those stores. All the pairs together first, then each alone.
A candidate for the exact judge, never a verdict."""
import re

from .csource import _blank, find

FAMILY = 'held_symbol_store_pointer'
FAMILIES = (FAMILY,)
LIMIT = 6
_TYPE = {'sb': 'u8', 'sh': 's16', 'sw': 's32'}
_VALUE = r'[\w]+|-\s*[\w]+'


def held_stores(asm):
    """{symbol: (width at 0, {offset: width})} for the stores through a register made from the symbol's address."""
    held, found = {}, {}
    for line in (asm or '').splitlines():
        text = re.sub(r'/\*.*?\*/', '', line).strip()
        made = re.match(r'addiu\s+(\$\w+)\s*,\s*\$\w+\s*,\s*%lo\(\s*([A-Za-z_]\w*)\s*\)', text)
        if made:
            held[made[1]] = made[2]
            continue
        store = re.match(r'(sb|sh|sw)\s+\$\w+\s*,\s*(-?(?:0x[0-9A-Fa-f]+|\d+))?\((\$\w+)\)', text)
        if store:
            sym = held.get(store[3])
            if sym:
                found.setdefault(sym, {})[int(store[2] or '0', 0)] = _TYPE[store[1]]
            continue
        if text.startswith(('jal', 'glabel', '.')):
            held.clear()
            continue
        written = re.match(r'(?!s[bhw]\b|b|j)[a-z][\w.]*\s+(\$\w+)\s*,', text)
        if written:
            held.pop(written[1], None)
    return {sym: (offsets[0], {k: v for k, v in offsets.items() if k})
            for sym, offsets in found.items() if 0 in offsets and len(offsets) > 1}


def _address(name):
    hit = re.fullmatch(r'(?:D|lbl)_([0-9A-Fa-f]{8})', name)
    return int(hit[1], 16) if hit else None


def _second(sym, offsets):
    """A pattern for the statement after `sym = v;`: a store `offset` bytes from `sym`, one of the target's."""
    forms = []
    for offset in offsets:
        sign, size = ('-', -offset) if offset < 0 else (r'\+', offset)
        number = rf'(?:0[xX]0*{size:X}|0[xX]0*{size:x}|{size})'
        forms.append(rf'\*[()\s\w*]*?&\s*{re.escape(sym)}[()\s]*{sign}\s*{number}[()\s]*=\s*(?P<v{len(forms)}>{_VALUE})\s*;')
        base = _address(sym)
        if base is not None:
            other = rf'(?:D|lbl)_(?i:{base + offset:08X})'
            forms.append(rf'{other}\s*=\s*(?P<v{len(forms)}>{_VALUE})\s*;')
        else:
            forms.append(rf'(?!)(?P<v{len(forms)}>)')
    return '|'.join(forms)


def _pointer(source):
    for name in ('p', 'held', 'held_ptr'):
        if not re.search(rf'\b{name}\b', source):
            return name
    return None


def variants(source, name, asm=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    pointer = _pointer(source)
    sites = []
    for sym, (first, rest) in sorted(held_stores(asm).items()):
        offsets = sorted(rest)
        pattern = re.compile(rf'(?<![\w.>&*\]])(?<!\* ){re.escape(sym)}\s*=\s*(?P<first>{_VALUE})\s*;\s*(?:{_second(sym, offsets)})')
        for hit in pattern.finditer(clean, span[0], span[1]):
            # the store must be a statement of its own, in a list where a block may stand
            before = clean[:hit.start()].rstrip()
            if not before.endswith((';', '{', '}', ':')):
                continue
            index = next(i for i in range(len(offsets) * 2) if hit[f'v{i}'] is not None)
            offset = offsets[index // 2]
            step = f'- {-offset:#x}' if offset < 0 else f'+ {offset:#x}'
            if pointer is None:
                return []
            block = (f'{{ u8 *{pointer}; do {{ {pointer} = (u8 *) &{sym}; }} while (0); '
                     f'*({first} *) {pointer} = {hit["first"]}; '
                     f'*({rest[offset]} *) ({pointer} {step}) = {hit[f"v{index}"]}; }}')
            sites.append((hit.start(), hit.end(), block))
    groups = ([sites] if len(sites) > 1 else []) + [[site] for site in sites]
    out = []
    for group in groups[:LIMIT]:
        child = source
        for start, end, text in sorted(group, reverse=True):
            child = child[:start] + text + child[end:]
        out.append((FAMILY, child))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
