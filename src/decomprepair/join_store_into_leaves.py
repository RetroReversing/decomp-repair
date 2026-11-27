"""The store after an `if`/`else` tree, written at the end of every branch that reaches it.

    if (fresh) {                          if (fresh) {
        if (easy) { lives = 3; }              if (easy) { lives = 3; do { level = 0; } while (0); }
        else      { lives = 2; }              else      { lives = 2; do { level = 0; } while (0); }
    } else {                      ->      } else {
        total = saved;                        total = saved;
    }                                         do { level = 0; } while (0);
    level = 0;                            }
    if (a || b) { level = pick; }         if (a || b) { level = pick; }

SN64 GCC 2.8.1 (`sn-n64-281 -G0 -mips3 -O2`, N64): with one store after the tree, the second cse pass skips around the
`||`'s second test and reuses the `%hi` of the stored symbol for the later store in the arm, which then lives in a
register across the tests. The target built the address again (`lui` for each store): the game wrote the store in each
branch, the join label then starts a block of its own, and the final jump pass cross-jumps the copies back into one.
The reuse was read in the cse2 dump; that the empty loop keeps the scheduler from lifting a branch's copy above its
loads, so that the tails stay identical, is a hypothesis. A 288-instruction game initialiser: 1085 -> 0 with every copy
in `do { } while (0)`, 1235 (worse) with bare copies.

Only the branches that fall through get a copy, and a branch whose last statement is itself an `if`/`else` tree gets it
in that tree's branches, so every path that reached the store still runs it once.

Children (`join_store_into_leaves`): for each braced `if`/`else` tree followed by an assignment with no call, the copies
wrapped, then bare; for a nested tree also the two for its outer arms alone. At most `LIMIT`.
"""
import re

from .arm_block_support import arm_chain, brace_pairs, statements
from .integer_repair_support import edit, view

FAMILY = 'join_store_into_leaves'
FAMILIES = (FAMILY,)
LIMIT = 12

ASSIGN = re.compile(r'[^;{}]*(?:[^=!<>]=(?!=)|<<=|>>=)[^;{}]*;\Z')
CALL = re.compile(r'\b(?!(?:if|while|for|switch|return|sizeof)\b)[A-Za-z_]\w*\s*\(')
CAST = re.compile(r'\(\s*(?:(?:unsigned|signed|const|volatile|struct)\s+)*[A-Za-z_]\w*\s*\**\s*\)')
# a statement that is not a plain store: a keyword, a label, or a declaration (`s32 x = 0;`, `T *p = q;`)
OTHER = re.compile(r'(?:if|for|while|do|switch|return|goto|break|continue|case|default)\b'
                   r'|[A-Za-z_]\w*\s*:(?!:)|[A-Za-z_]\w*(?:\s+|\s*\*+\s*(?=[A-Za-z_]\w*\s*=))\**\s*[A-Za-z_]')
EXIT = re.compile(r'(?:return\b[^;]*|goto\s+\w+|break|continue)\s*;\Z')


def _tree(clean, closes, span):
    """The branch blocks of the statement at `span` when it is a braced `if`/`else` tree, else None."""
    start, end = span
    if not re.match(r'if\b', clean[start:end]) or clean[end - 1] != '}':
        return None
    return arm_chain(clean, closes, end - 1)


def _leaves(clean, closes, block):
    """(closing brace of each falling-through branch end under `block`, the blocks passed through)."""
    opening, closing = block
    inner = statements(clean, opening + 1, closing)
    if inner:
        nested = _tree(clean, closes, inner[-1])
        if nested:
            ends, passed = [], [block]
            for child in nested:
                more, seen = _leaves(clean, closes, child)
                ends += more
                passed += seen
            return ends, passed
        if EXIT.match(clean[inner[-1][0]:inner[-1][1]]):
            return [], [block]
    return [closing], [block]


def _declares(text, names):
    return any(re.search(r'\b(?!(?:return|else|do)\b)[A-Za-z_]\w*[\s*]+' + re.escape(word) + r'\s*(?=[=;\[,])', text)
               for word in names)


def _appended(source, closing, statement):
    """The edit that writes `statement` as the last line of the block closing at `closing`."""
    line = source.rfind('\n', 0, closing) + 1
    if source[line:closing].strip():  # the brace shares its line with code
        return closing, closing, ' ' + statement + ' '
    return line, line, source[line:closing] + '    ' + statement + '\n'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if pairs is None:
        return []
    closes = {close: open_ for open_, close in pairs.items()}
    out = []
    for opening, closing in sorted(pairs.items()):
        found = statements(clean, opening + 1, closing)
        for tree, store in zip(found, found[1:]):
            text = clean[store[0]:store[1]]
            if not ASSIGN.match(text) or OTHER.match(text) or CALL.search(CAST.sub(' ', text)):
                continue
            arms = _tree(clean, closes, tree)
            if not arms or clean[tree[1]:store[0]].strip():
                continue
            names = set(re.findall(r'(?<![.\w>])[A-Za-z_]\w*', CAST.sub(' ', text)))
            deep, passed = [], []
            for arm in arms:
                ends, seen = _leaves(clean, closes, arm)
                deep += ends
                passed += seen
            if _declares(' '.join(clean[a:b] for a, b in passed), names):
                continue  # a branch's own local would capture the name
            shallow = [b for a, b in arms
                       if not (inner := statements(clean, a + 1, b)) or not EXIT.match(clean[inner[-1][0]:inner[-1][1]])]
            statement = source[store[0]:store[1]]
            line = source.rfind('\n', 0, store[0]) + 1
            after = store[1]
            if not source[line:store[0]].strip() and source[after:after + 1] == '\n':
                removal = (line, after + 1, '')  # the whole line goes
            else:
                removal = (store[0], after, '')
            for ends in [deep] if deep == shallow else [deep, shallow]:
                if not ends:
                    continue
                for copy in ('do { ' + statement + ' } while (0);', statement):
                    changes = [_appended(source, end, copy) for end in ends] + [removal]
                    out.append((FAMILY, edit(source, changes)))
            if len(out) >= LIMIT:
                return out[:LIMIT]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring
