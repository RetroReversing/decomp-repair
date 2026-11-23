"""A size summed into a call, and the pointer cursor after it, kept in the one variable the game used.

m2c writes an allocation as

    p = alloc((((((a + 0xB8) + a) + b) + c) + d) + d, 0x21);
    if (p != NULL) {
        q1 = p + 0xB8;     store(q1);
        q2 = q1 + a;       store(q2);
        q3 = q2 + a;       store(q3);

with a fresh temporary for every link of the cursor chain. The game kept one running variable: the size accumulated in
it (`p = 0xB8; p += a; p += a; ...`), the allocation's result assigned to the same variable, and the cursor stepped on
in place (`p += 0xB8; store(p); p += a; store(p)`). One variable is one pseudo for the register allocator: in a
392-instruction object initialiser the size, the heap result and every cursor value took the same saved register, and
the literal's `li` was the first insn of the sum (gcc folds `a + 0xB8` into an `addiu` otherwise). Together the two
rewrites took 5877 -> 5692 -> 5282 there (with the `short` temporary of the same chain widened).

Two rewrites, offered together first and then each alone (at most 3 children):

- the cursor chain: a statement `k = j + expr;` where `k` has not been used before and `j` is not used after, both
  declared with the same integer or `void *`/`char *`/`u8 *` type and the statement is not inside a loop, becomes
  `j += expr;` and the later uses of `k` become `j` (repeatedly, so the whole chain collapses into its first variable);
- the sum: a call argument that is a sum of four or more terms with one literal, assigned to `p`, becomes
  `p = (__typeof__ (p)) LITERAL;` at the top of the block that holds the call (`p` must not be used before the call
  there), `p += term;` for each term but the last and `p = call(p + last, ...)`.

Hypotheses read off one compiler's code (KMC GCC 2.7.2): that the game used one variable is inferred from the shared
register and the `li` that starts the sum."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'running_total_cursor'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
SIMPLE = r'(?:void\s*\*|char\s*\*|u8\s*\*|s8\s*\*|s32|u32|int|unsigned\s+int|unsigned|long|unsigned\s+long)'
LINK = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<k>{IDENT})[ \t]*=[ \t]*(?P<j>{IDENT})[ \t]*\+[ \t]*(?P<expr>[^;{{}}=\n]+);[ \t]*\n')
CALL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<p>{IDENT})[ \t]*=[ \t]*(?P<callee>{IDENT})[ \t]*\(')
NUMBER = re.compile(r'^(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*$')
LIMIT = 3


def _declared(clean, start, end, name):
    hit = re.search(rf'(?m)^[ \t]*({SIMPLE})[ \t]*(?<![\w])\**{re.escape(name)}[ \t]*;', clean[start:end])
    return re.sub(r'\s+', ' ', hit[1]) if hit else None


def _words(text, name):
    return [m.start() for m in re.finditer(rf'(?<![\w.]){re.escape(name)}(?!\w)', text)]


def _in_loop(clean, start, at):
    """Whether the text at `at` lies inside the body of a loop (conservative: any enclosing block opened by one)."""
    depth, i = 0, at
    while i > start:
        i -= 1
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if depth == 0:
                head = clean[max(start, i - 80):i].rstrip()
                if re.search(r'(?:\bdo|\bfor\s*\([^;{}]*\)|\bwhile\s*\([^;{}]*\))$', head) or re.search(r'\bfor\s*\(', head[-60:]):
                    return True
            else:
                depth -= 1
    return False


def _collapse_chain(source, span):
    """The source with one cursor link collapsed into its predecessor, or None."""
    clean = _blank(source)
    body_start, body_end = span
    for link in LINK.finditer(clean, body_start, body_end):
        k, j = link['k'], link['j']
        if k == j or re.search(rf'(?<![\w.]){re.escape(k)}\b', link['expr']) or ('=' in link['expr']):
            continue
        kind_k, kind_j = _declared(clean, body_start, body_end, k), _declared(clean, body_start, body_end, j)
        if not kind_k or kind_k != kind_j or (kind_j.endswith('*') and not re.match(r'(?:void|char|u8|s8)', kind_j)):
            continue
        before = clean[body_start:link.start()]
        after = clean[link.end():body_end]
        declaration = re.search(rf'(?m)^[ \t]*{SIMPLE}[ \t]*\**{re.escape(k)}[ \t]*;[ \t]*\n', before)
        if not declaration or len(_words(before, k)) != 1 or _words(after, j) or _in_loop(clean, body_start, link.start()):
            continue
        out = source[:body_start + declaration.start()] + source[body_start + declaration.end():link.start()]
        out += f"{link['indent']}{j} += {link['expr'].strip()};\n"
        out += re.sub(rf'(?<![\w.]){re.escape(k)}(?!\w)', j, source[link.end():])
        return out
    return None


def _terms(text):
    """The terms of a left-nested sum `(((a + b) + c) + d)`, or None."""
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    depth, cut = 0, None
    for i in range(len(text) - 1, -1, -1):
        c = text[i]
        depth += (c == ')') - (c == '(')
        if depth == 0 and c == '+' and (i == 0 or text[i - 1] not in '+-'):
            cut = i
            break
    if cut is None:
        return [text] if text and not re.search(r'[+]', text.replace('++', '')) else None
    head = _terms(text[:cut])
    tail = text[cut + 1:].strip()
    if head is None or not tail or re.search(r'\+(?!\+)', re.sub(r'\([^()]*\)', '', tail)):
        return None
    return head + [tail]


def _sum_to_variable(source, span):
    clean = _blank(source)
    for call in CALL.finditer(clean, span[0], span[1]):
        p = call['p']
        open_at = call.end() - 1
        end = close(clean, open_at)
        if not end or clean[end:end + 1] != ';' and not re.match(r'\s*;', clean[end:]):
            continue
        first, comma = None, None
        depth = 0
        for i in range(open_at + 1, end - 1):
            c = clean[i]
            depth += (c == '(') - (c == ')')
            if depth == 0 and c == ',':
                comma = i
                break
        if comma is None:
            continue
        first = source[open_at + 1:comma]
        terms = _terms(first)
        if not terms or len(terms) < 4 or re.search(rf'\b{IDENT}\s*\(', ''.join(t for t in terms if not t.startswith('('))):
            continue
        literals = [t for t in terms if NUMBER.match(t.strip())]
        if len(literals) != 1 or p in re.findall(IDENT, first):
            continue
        kind = _declared(clean, span[0], span[1], p)
        if not kind or (kind.endswith('*') and not re.match(r'(?:void|char|u8|s8)', kind)):
            continue
        ordered = literals + [t for t in terms if t is not literals[0]]
        # the block holding the call: its `{` is the nearest unmatched one before the statement
        depth, i = 0, call.start()
        while i > span[0]:
            i -= 1
            if clean[i] == '}':
                depth += 1
            elif clean[i] == '{':
                if depth == 0:
                    break
                depth -= 1
        top = source.find('\n', i) + 1
        if _words(clean[top:call.start()], p) or _in_loop(clean, span[0], call.start()):
            continue
        indent = call['indent']
        rest = source[comma:end]
        steps = ''.join(f'{indent}{p} += {t.strip()};\n' for t in ordered[1:-1])
        head = f'{indent}{p} = (__typeof__ ({p})) {ordered[0].strip()};\n'
        call_text = f'{indent}{p} = {call["callee"]}({p} + {ordered[-1].strip()}{rest}'
        tail = source[end:]
        return source[:top] + head + source[top:call.start()] + steps + call_text + tail
    return None


def variants(source, name):
    """Proposals: the cursor chain collapsed and the sum accumulated in the result variable, together first."""
    span = find(source, name)
    if not span:
        return []
    texts = []
    chained = source
    for _ in range(12):
        again = _collapse_chain(chained, find(chained, name))
        if again is None:
            break
        chained = again
    summed = _sum_to_variable(source, span)
    both = _sum_to_variable(chained, find(chained, name)) if chained != source else None
    for text in (both, chained if chained != source else None, summed):
        if text and text != source:
            texts.append(text)
    return [(FAMILY, text) for text in dict.fromkeys(texts)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 59}
