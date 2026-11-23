"""A local assigned on the line after the statement that reads it: the assignment goes first.

m2c names the address of a field it saw used twice and prints the assignment where the use order put it, which can be
after the first use (the compound assignment `*(u16 *)((char *)(p) + 0x1BC) += tbl[i * 2];` and then `p = base + i * 2;`).
The draft reads an uninitialised local there: gcc compiles that to a store through whatever register the local gets
(a saved register nobody set), which no game did, and every register-allocation row after it is shifted by that
local's live range. Two spellings of the order the game had are offered:

    p = base + i * 2;                         (the assignment first, on its own line)
    *(u16 *)((char *)(p) + 0x1BC) += ...;

    *(u16 *)((char *)(p = base + i * 2) + 0x1BC) += ...;     (the assignment inside the use)

The second is where the sum is evaluated with the table read on the right (`tbl[i * 2]` is loaded before the address is
formed, so the pointer's `addu` follows the halfword load in the schedule), the first where it comes before it; which
one a function needs is the judge's to say. Only for a local with no other mention before the use, an assignment that
reads nothing the statement changes, and a statement without a call or an increment.
"""
import re

from . import narrow_table_addend
from .integer_repair_support import IDENT, edit, view

FAMILY = 'assign_after_use_swap'
FAMILIES = (FAMILY,)

LIMIT = 8
_PAIR = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<use>[^;{}\n]*;)[ \t]*\n'
    r'(?P<indent2>[ \t]*)(?P<local>' + IDENT + r')[ \t]*=(?!=)[ \t]*(?P<expr>[^;{}\n]+);[ \t]*\n')


def _calls(text):
    """A call: a name followed by a bracket (a cast like `(char *)` is not one: its bracket comes first)."""
    return re.search(rf'(?<![\w.>)\]])\s*(?<!\bsizeof)\b(?!if\b|while\b|for\b|switch\b|return\b){IDENT}\s*\(', text) is not None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, base = part.clean, part.opening + 1
    body = clean[base:part.end]
    result = []
    for hit in _PAIR.finditer(body):
        local = hit['local']
        use, expression = hit['use'], hit['expr']
        mention = re.search(rf'(?<![\w.>]){re.escape(local)}\b', use)
        if not mention or len(re.findall(rf'(?<![\w.>]){re.escape(local)}\b', use)) != 1:
            continue
        if re.search(rf'(?<![\w.>]){re.escape(local)}\b', expression) or _calls(use) or _calls(expression) \
                or re.search(r'\+\+|--', use + expression):
            continue
        declaration = re.search(
            rf'(?m)^[ \t]*[A-Za-z_][\w \t*]*?[ \t*]{re.escape(local)}[ \t]*;[ \t]*$', body[:hit.start()])
        if not declaration:
            continue
        before = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', body[:hit.start()])
                  if not declaration.start() <= m.start() < declaration.end()]
        if before:
            continue
        # the use is a store or a read-modify-write through the local; an assignment line that follows is the m2c order
        at = base + hit.start()
        use_at = base + hit.start('use')
        sliced = source[use_at:base + hit.end('use')]
        assigned = source[base + hit.start('expr'):base + hit.end('expr')].strip()
        first = f"{source[base + hit.start('indent2'):base + hit.start('local')]}{local} = {assigned};\n"
        swapped = edit(source, [(at, base + hit.end(), f"{first}{source[base + hit.start('indent'):base + hit.end('use')]}\n")])
        inline_at = use_at + re.search(rf'(?<![\w.>]){re.escape(local)}\b', sliced).start()
        inlined = edit(source, [(inline_at, inline_at + len(local), f'({local} = {assigned})'),
                                (base + hit.end('use'), base + hit.end(), '\n')])
        for text in (swapped, inlined):
            if text != source and (FAMILY, text) not in result:
                result.append((FAMILY, text))
            # the swap alone changes nothing the judge can see while a signed table read is added into the
            # halfword store (`lhu` for the game's `lh`): the combination is one child
            wide = narrow_table_addend.widen(text, name, header)
            if wide and (FAMILY, wide) not in result:
                result.append((FAMILY, wide))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
