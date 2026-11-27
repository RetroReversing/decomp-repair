"""Byte-offset stores to word-declared symbols in a loop, with the bases and the stored constant held in locals.

m2c writes a loop that clears or marks bytes of two tables as `*(s8 *)(i + &D_A) = 1;` and `p = (s32 *)(i + &D_B); ...
*p = 0;`. The symbols are `extern M2C_UNK` (one word), so C scales `i` by four again, and the draft's word pointer
makes the second store a `sw`. The target is byte arithmetic on integers: the two addresses and the stored 1 live in
registers set before the loop (`lui/addiu $t0, D_A`, `addiu $a3, $zero, 1`, `lui/addiu $a2, D_B`), `addu $v0, $v1, $t0;
sb $a3, ($v0)`, `addu $v1, $v1, $a2; sb $zero, ($v1)`, with no `sll`. KMC GCC 2.7.2 `-O1` does not hoist a symbol's address
or a stored constant out of a loop by itself (it folds `%lo` into the store), so the original held them in locals, set in
the order the registers were taken: first address, the constant, second address (300 -> 0 on an N64 function of two
nested counted loops):

    base1 = (s32)&D_A;  val = 1;  base2 = (s32)&D_B;          (before the loop)
    temp_v1 = i + j;
    *(s8 *)(temp_v1 + base1) = val;
    temp2 = (s8 *)(temp_v1 + base2);  ...  *temp2 = 0;

None of the single steps improves (the integer bases alone are 300 -> 520: the stores are still words and the addresses
are rebuilt in the loop), so the family offers the whole idea as one child.

word_symbol_loop_bases
    For the symbols declared `M2C_UNK`, `M2C_UNK32`, `s32`, `u32` or `int` that are added to an index (`(idx + &SYM)` or
    `(&SYM + idx)`) inside a `do`/`for`/`while` block: an `s32 baseN` per symbol set to `(s32)&SYM` before the outermost such
    loop, the sums using it, the first literal stored through such a sum held in a local of the store's type that is
    set after the first base, and a local word pointer that is set to such a sum and only stored through (`*p = 0;`) narrowed
    to the type of the byte store that shares the loop.
word_symbol_loop_bases_plain
    The same without the constant's local.

A candidate for the exact judge, which also decides whether the narrowed store is the game's.
"""
import re

from .frame_padding_repairs import declaration_ends
from .integer_repair_support import IDENT, edit, view

FAMILY = 'word_symbol_loop_bases'
PLAIN_FAMILY = 'word_symbol_loop_bases_plain'
FAMILIES = (FAMILY, PLAIN_FAMILY)
_WORDS = r'(?:M2C_UNK|M2C_UNK32|s32|u32|int)'
_DECLARATION = re.compile(rf'(?m)^[ \t]*extern\s+{_WORDS}\s+(?P<name>{IDENT})\s*;')
_NARROW = {'s8': 's8', 'u8': 'u8', 'char': 'char'}
_LITERAL = r'(?:0[xX][0-9a-fA-F]+|\d+)'


def _loop_start(clean, low, position):
    """The offset where the outermost `do`/`for`/`while` block around `position` starts its statement, or None."""
    stack, boundary, depth = [], low, 0
    for at in range(low, position):
        ch = clean[at]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == '{':
            stack.append(clean[boundary:at])
            stack[-1] = (boundary, stack[-1])
            boundary = at + 1
        elif ch == '}':
            if stack:
                stack.pop()
            boundary = at + 1
        elif ch == ';' and depth == 0:
            boundary = at + 1
    for start, header in stack:
        if re.match(r'\s*(?:do|for\b[^{}]*|while\b[^{}]*)\s*$', header):
            return start + len(header) - len(header.lstrip())
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, low = part.clean, part.opening + 1
    words = {m['name'] for m in _DECLARATION.finditer(clean)}
    if not words:
        return []
    sites = []
    for found in re.finditer(rf'\(\s*(?P<a>[^()&;=]+?)\s*\+\s*&\s*(?P<s1>{IDENT})\s*\)|'
                             rf'\(\s*&\s*(?P<s2>{IDENT})\s*\+\s*(?P<b>[^()&;=]+?)\s*\)', clean[:part.end]):
        symbol = found['s1'] or found['s2']
        if found.start() < low or symbol not in words:
            continue
        start = _loop_start(clean, low, found.start())
        if start is None:
            continue
        sites.append((found, symbol, start))
    if not sites:
        return []
    loop = min(start for _, _, start in sites)
    sites = [site for site in sites if site[2] == loop]
    order = list(dict.fromkeys(symbol for _, symbol, _ in sites))
    names = {symbol: f'base{k + 1}' for k, symbol in enumerate(order)}
    body = clean[low:part.end]
    if any(re.search(rf'\b{n}\b', body) for n in names.values()) or re.search(r'\bval\b', body):
        return []
    edits = []
    for found, symbol, _ in sites:
        at = found.start('s1') if found['s1'] else found.start('s2')
        amp = clean.rfind('&', found.start(), found.end()) if found['s1'] else clean.find('&', found.start())
        edits.append((amp, at + len(symbol), names[symbol]))
    # the first literal stored through such a sum
    store = next((m for m in re.finditer(rf'\*\s*\(\s*(?P<type>s8|u8|char|s16|u16)\s*\*\s*\)\s*(?P<sum>\([^;]*\))\s*=\s*(?P<value>{_LITERAL})\s*;',
                                        clean[:part.end])
                  if any(m.start('sum') <= f.start() < m.end('sum') for f, _, _ in sites)), None)
    narrow = _narrowing(clean, low, part.end, sites, store)
    line = clean.rfind('\n', 0, loop) + 1
    indent = re.match(r'[ \t]*', clean[line:]).group(0)
    ends = declaration_ends(part)
    if not ends:
        return []
    children = []
    for family, constant in ((FAMILY, store), (PLAIN_FAMILY, None)):
        if family == FAMILY and not store:
            continue
        lines = [f'{indent}{names[symbol]} = (s32)&{symbol};\n' for symbol in order]
        declarations = [f's32 {names[symbol]};' for symbol in order]
        more = list(edits)
        if constant:
            lines.insert(1, f'{indent}val = {constant["value"]};\n')
            declarations.append(f'{constant["type"]} val;')
            more.append((constant.start('value'), constant.end('value'), 'val'))
        indentation = re.match(r'[ \t]*', clean[clean.rfind('\n', 0, ends[-1]) + 1:]).group(0)
        more.append((ends[-1], ends[-1], ''.join(f'\n{indentation}{d}' for d in declarations)))
        more.append((line, line, ''.join(lines)))
        more += narrow
        children.append((family, edit(part.source, more)))
    return children


def _narrowing(clean, low, end, sites, store):
    """Edits that give a word pointer local, only set to a site's sum and only stored through, the byte type of `store`."""
    if not store:
        return []
    kind = store['type']
    edits = []
    for found in re.finditer(rf'(?P<name>{IDENT})\s*=\s*\(\s*(?P<cast>{_WORDS})\s*\*\s*\)\s*(?P<sum>\([^;]*\))\s*;', clean[:end]):
        if found.start() < low or not any(found.start('sum') <= f.start() < found.end('sum') for f, _, _ in sites):
            continue
        local = found['name']
        declaration = re.search(rf'(?m)^[ \t]*(?P<type>{_WORDS})\s*\*\s*{local}\s*;', clean[:end])
        uses = [u for u in re.finditer(rf'(?<![\w.>]){local}\b', clean[low:end])]
        stores = re.findall(rf'(?m)^[ \t]*\*\s*{local}\s*=\s*{_LITERAL}\s*;', clean[low:end])
        if not declaration or len(uses) != 2 + len(stores):
            continue
        edits.append((declaration.start('type'), declaration.end('type'), kind))
        edits.append((found.start('cast'), found.end('cast'), kind))
    return edits


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 1650}
