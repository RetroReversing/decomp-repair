"""A shift used twice in a sum: the chain `L + (v = X*4) + v + R` needs a first use of `v` that combine later erases.

m2c writes an allocation size as two groups, `((u32)((A * 8) + (v = T * 4))) + (R + v)`, with `v` assigned inline from a
shift and read once more. GCC 2.7.2 (KMC) written as the plain chain `A * 8 + (v = T * 4) + v + R` merges the two reads
into one shift of the sum (`(A + T) << 3`), which is worse (487 to 915 on the one function measured), and a redundant
use alone on the m2c shape did nothing (65). The target added the shared shift twice in a row (`sll v; addu; addu` then
the other term in the delay slot) and was exact with both together:

    A * 8 + (v = T * 4) + v + R + (v & 3)

Measured with the compiler's own binary under lldb (`try_combine` / `can_combine_p`; hypotheses, not confirmed in the
compiler source): flow links a shift's definition only from its first use, and combine's three-insn merge (shift,
first sum, second sum) needs that link. A first use that is not the first sum leaves the chain unmerged. `v & 3` is
such a use, and combine evaluates it to 0 because the low bits of `v` are known zero, so no trace is left in the
object code. (In a harness the same worked as a call's second argument, `0x2D + (v & 3)`, since arguments are
evaluated right to left. A store of `v` also blocks the merge but stays visible.)

- `shared_shift_chain`: the two-group shape flattened into the left chain (alone it is worse).
- `shared_shift_zero_use`: ` + (v & mask)` appended (`mask = 2^k - 1`; on the m2c shape alone it changes nothing).
- `shared_shift_combination`: the chain with the trailing mask, the shape that matched.
Guards: `v` assigned inline from `X * 2^k` or `X << k` (k 1 to 8), read exactly once more in the same expression, the
operands only pure (no assignment, increment, call or volatile). These are hypotheses for the exact judge."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('shared_shift_chain', 'shared_shift_zero_use', 'shared_shift_combination')
LIMIT = 8
SCALE = re.compile(r'^(?P<x>.+?)\s*(?:\*\s*(?P<mul>\d+)|<<\s*(?P<shift>\d+))\s*$', re.S)
IMPURE = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|\b[A-Za-z_]\w*\s*\(|\bvolatile\b')
CAST = re.compile(r'\(\s*(?:u32|s32|int|unsigned|unsigned int)\s*\)\s*$')


def _bits(rhs):
    hit = SCALE.match(rhs)
    if not hit:
        return 0
    if hit['mul']:
        n = int(hit['mul'])
        return n.bit_length()-1 if n & (n-1) == 0 and 2 <= n <= 256 else 0
    n = int(hit['shift'])
    return n if 1 <= n <= 8 else 0


def _pure(text):
    return not IMPURE.search(re.sub(r'\(\s*[A-Za-z_][\w ]*\*+\s*\)', '', text))


def _shapes(source, part):
    """(start, end, left, assign, right, var, mask) of each m2c two-group sum `((L + (v = X*2^k))) + (R + v)`."""
    clean = part.clean
    found = []
    for hit in re.finditer(rf'\(\s*({IDENT})\s*=\s*(?!=)', clean[part.opening+1:part.end]):
        a_open = part.opening+1+hit.start()
        a_close = close(clean, a_open)
        if not a_close:
            continue
        var = hit[1]
        rhs = clean[part.opening+1+hit.end():a_close-1].strip()
        bits = _bits(rhs)
        if not bits or not _pure(rhs):
            continue
        before = clean[:a_open].rstrip()
        if not before.endswith('+'):
            continue
        # group one: the parenthesis that opens before L and closes right after the assignment
        tail = re.match(r'\s*\)', clean[a_close:])
        if not tail:
            continue
        g1_close = a_close+tail.end()
        g1_open = None
        depth = 0
        for i in range(a_open-1, part.opening, -1):
            ch = clean[i]
            if ch == ')':
                depth += 1
            elif ch == '(':
                if depth == 0:
                    g1_open = i
                    break
                depth -= 1
        if g1_open is None or close(clean, g1_open) != g1_close:
            continue
        left = clean[g1_open+1:before.rindex('+')].strip()
        wrap = CAST.search(clean[:g1_open])
        outer = clean[:wrap.start()].rstrip() if wrap else ''
        closing = re.match(r'\s*\)', clean[g1_close:])
        if wrap and outer.endswith('(') and closing and close(clean, len(outer)-1) == g1_close+closing.end():
            g1_open, g1_close = len(outer)-1, g1_close+closing.end()  # `((u32) (L + v = ..))`
        second = re.match(r'\s*\+\s*\(', clean[g1_close:])
        if not second:
            continue
        g2_open = g1_close+second.end()-1
        g2_close = close(clean, g2_open)
        if not g2_close:
            continue
        inner = clean[g2_open+1:g2_close-1].strip()
        end_hit = re.search(rf'\+\s*{re.escape(var)}$', inner)
        if not end_hit:
            continue
        right = inner[:end_hit.start()].strip()
        if not left or not right or not _pure(left) or not _pure(right):
            continue
        if re.search(rf'\b{var}\b', left+' '+right):
            continue
        start = g1_open
        cast = CAST.search(clean[:g1_open])
        if cast:
            start = cast.start()
        if len(re.findall(rf'\b{var}\b', clean[start:g2_close])) != 2:
            continue
        found.append((start, g2_close, left, clean[a_open:a_close], right, var, (1 << bits)-1))
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    result = []
    for start, end, left, assign, right, var, mask in _shapes(source, part):
        chain = f'{left} + {assign} + {var} + {right}'
        result.append(('shared_shift_chain', edit(source, [(start, end, chain)])))
        result.append(('shared_shift_zero_use', edit(source, [(end, end, f' + ({var} & {mask})')])))
        result.append(('shared_shift_combination', edit(source, [(start, end, f'{chain} + ({var} & {mask})')])))
    seen, out = set(), []
    for family, text in result:
        if text != source and text not in seen:
            seen.add(text)
            out.append((family, text))
    return out[:LIMIT]
