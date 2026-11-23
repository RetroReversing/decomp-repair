"""Two stores of one value through two pointers, written as one chained assignment (`b = a = v;`).

m2c writes `*p = v; *q = v;` as two statements, each re-reading the pointers it goes through. The game's C often
stored a value through two records in one expression, `q->x = p->x = v;`: gcc 2.7.2 expands the outer target's
address first, then the inner assignment (its address, the value, the store), then the outer store, so both pointers
are loaded before either store and the two stores follow each other with no reload between. Written as two statements
the second target's pointer is loaded again after the first store (a float store may alias it), which moves the loads
and changes the registers of the whole group. In a 392-instruction object initialiser the three pairs of a
vertex-copy loop were the change that took 5232 to 4577 (the loop's rows all matched).

`variants` offers every pair of adjacent assignment statements that store the same plain variable (not a literal), whose
two targets contain no call, as `second = first = value;`, all pairs together first and then each alone (at most 6).
The chained form leaves the order of the two targets' address reads to the compiler; that it is the game's source is a
hypothesis read off one compiler's code (KMC GCC 2.7.2)."""
import re

from .csource import _blank, find

FAMILY = 'paired_store_chain'
FAMILIES = (FAMILY,)
LIMIT = 6
IDENT = r'[A-Za-z_]\w*'
PAIR = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<first>[^;{{}}\n=][^;{{}}\n]*?)\s=\s(?P<value>{IDENT});[ \t]*\n'
                  rf'[ \t]*(?P<second>[^;{{}}\n=][^;{{}}\n]*?)\s=\s(?P=value);[ \t]*\n')
CALL = re.compile(rf'\b{IDENT}\s*\(')


def _target(text):
    """A store target worth chaining: it dereferences or indexes something, and calls nothing."""
    return bool(re.search(r'[*\[]|->', text)) and not CALL.search(text) and '=' not in text


def variants(source, name):
    """Proposals: every qualifying pair as one chained assignment, all together first and then each alone."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    pairs, position = [], span[0]
    while True:
        hit = PAIR.search(clean, position, span[1])
        if not hit:
            break
        position = hit.end(0) - 1 - len(hit['second']) - len(hit['value']) - 5  # (the second store may open the next pair)
        position = max(position, hit.start() + 1)
        if (_target(hit['first']) and _target(hit['second']) and hit['first'].strip() != hit['second'].strip()
                and hit['value'] not in re.findall(IDENT, hit['first'] + ' ' + hit['second'])):
            pairs.append(hit)
    chosen, last = [], -1
    for hit in pairs:  # (disjoint pairs only: a store shared by two pairs takes the first)
        if hit.start() >= last:
            chosen.append(hit)
            last = hit.end()
    if not chosen:
        return []

    def write(hits):
        out, at = [], 0
        for hit in hits:
            out.append(source[at:hit.start()])
            out.append(f"{hit['indent']}{source[hit.start('second'):hit.end('second')].strip()} = "
                       f"{source[hit.start('first'):hit.end('first')].strip()} = {hit['value']};\n")
            at = hit.end()
        out.append(source[at:])
        return ''.join(out)

    texts = [write(chosen)] + ([write([hit]) for hit in chosen] if len(chosen) > 1 else [])
    return [(FAMILY, text) for text in dict.fromkeys(texts)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 57}
