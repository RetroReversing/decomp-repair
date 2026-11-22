"""An operand held in a local that is dead there, so the allocator treats it as a pseudo of two blocks.

gcc 2.7.2's local allocator only owns pseudos that live and die in one basic block; it ties a result to a dying first
operand and orders its quantities by priority. A value kept in a local the function also uses elsewhere (m2c reuses
`temp_a0` for unrelated values) is a global pseudo: allocated later, never tied, scheduled early. A sequencer function
needed four such stagings from 195 to exact: the factor of a product in the call-result local (the product's register
moved: `mflo $v1`), the masked value in the loop's `a0` local (not the block-local temporary that took `$v0`), a load
in the loop's node pointer (`$a1` instead of `$a0`), and the three loads of the last update through one local (their
order and `$v1`). The compound or loaded operand of `x = A op B;` or `*p op= B;` is offered in each local that is dead
at the statement, the loop's next iteration included.

A local is dead after a statement when every later read is covered by an assignment in an enclosing block before it,
the first mention around the loop's back edge and after the loop included. Integer locals take any operand; a
pointer local takes a loaded operand (`m = (void *) *p;`) and is read back as `(u32)`.
"""
import re

from .csource import _blank, find
from .global_pointer_run_repairs import _blocks, _statements
from .pattern_repairs import close
from .product_operand_reuse_repairs import _binary_operators, _compound, _strip

FAMILY = 'dead_local_stage'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
INTEGER = re.compile(r'(?m)^[ \t]*(?:register\s+)?(?:(?:unsigned|signed)\s+)?(?:long|int|u32|s32)\s+(' + IDENT + r')\s*;')
POINTER = re.compile(r'(?m)^[ \t]*(?:register\s+)?[A-Za-z_][\w ]*\*+[ \t]*(' + IDENT + r')\s*;')
ASSIGN = re.compile(r'(?P<dest>[^=;{}]+?)\s*(?P<op>[-+*&|^]|<<|>>)?=(?!=)\s*(?P<value>[^;{}]+);')


def _mentions(text, name, lo, hi):
    return [(m.start(), m) for m in re.finditer(r'(?<![\w.>])' + name + r'\b', text) if lo <= m.start() < hi]


def _is_write(text, hit):
    """True for `name = ...;` where the right side does not read the name."""
    after = text[hit.end():hit.end() + 400]
    assigned = re.match(r'\s*=(?!=)\s*([^;]*);', after)
    before = text[max(0, hit.start() - 2):hit.start()]
    return bool(assigned) and not re.search(r'(?<![\w.>])' + re.escape(hit.group()) + r'\b', assigned[1]) \
        and not re.search(r'[-+*&|^<>]$', before.strip()[-1:] if before.strip() else '')


def _block_of(blocks, position):
    """The innermost (start, end) block holding a position."""
    best = None
    for a, b in blocks:
        if a <= position < b and (best is None or b - a < best[1] - best[0]):
            best = (a, b)
    return best


def _covered(clean, blocks, name, sequence):
    """True when each read in the mention sequence has an earlier write whose block contains it."""
    writes = []
    for position in sequence:
        hit = re.compile(r'(?<![\w.>])' + name + r'\b').match(clean, position)
        if _is_write(clean, hit):
            writes.append(position)
            continue
        if not any(_block_of(blocks, w) and _block_of(blocks, w)[0] <= position < _block_of(blocks, w)[1] for w in writes):
            return False
    return True


def _loops(clean, opening, end):
    """The (start, end) of each loop body, `do {`, `while (...) {` and `for (...) {`."""
    result = []
    for loop in re.finditer(r'\b(?:do|while|for)\b', clean[opening:end]):
        at = opening + loop.end()
        if loop.group() != 'do':
            while at < end and clean[at].isspace():
                at += 1
            if at >= end or clean[at] != '(':
                continue
            stop = close(clean, at)
            if not stop:
                continue
            at = stop
        while at < end and clean[at].isspace():
            at += 1
        if at < end and clean[at] == '{':
            last = close(clean, at, '{', '}')
            if last:
                result.append((at + 1, last - 1))
    return result


def _dead(clean, opening, end, blocks, loops, name, stop, start):
    """The local holds nothing live after the statement that ends at `stop` (and starts at `start`)."""
    later = [p for p, _ in _mentions(clean, name, stop, end)]
    inner = [lp for lp in loops if lp[0] <= start < lp[1]]
    paths = []
    if inner:
        loop = min(inner, key=lambda lp: lp[1] - lp[0])
        within = [p for p in later if p < loop[1]]
        wrap = [p for p, _ in _mentions(clean, name, loop[0], start)]
        outside = [p for p in later if p >= loop[1]]
        paths = [within + wrap, within + outside]
    else:
        paths = [later]
    return all(_covered(clean, blocks, name, path) for path in paths)


def _spans(clean, hit):
    """The absolute (start, end) of each operand worth staging in an assignment statement."""
    value = hit.start('value'), hit.end('value')
    text = clean[value[0]:value[1]]
    lead = len(text) - len(text.lstrip())
    trimmed = (value[0] + lead, value[1] - (len(text) - len(text.rstrip())))
    spans = []
    if hit['op']:
        spans.append(trimmed)
    found = _binary_operators(text.strip())
    if len(found) == 1:
        position, operator = found[0]
        base = trimmed[0]
        left = text.strip()[:position]
        right = text.strip()[position + len(operator):]
        spans.append((base, base + len(left.rstrip())))
        spans.append((base + position + len(operator) + (len(right) - len(right.lstrip())), trimmed[1]))
    return spans


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    integers = INTEGER.findall(body)
    pointers = POINTER.findall(body)
    blocks = list(_blocks(clean, opening, end))
    loops = _loops(clean, opening, end)
    result = _reuse_initialized_load(source, clean, opening, end, blocks, integers)
    for first, last in blocks:
        for start, stop in _statements(clean, first, last):
            hit = ASSIGN.fullmatch(clean, start, stop)
            if not hit or re.match(r'\s*(?:return|goto|case)\b', clean[start:stop]):
                continue
            for a, b in _spans(clean, hit):
                operand = clean[a:b]
                stripped = _strip(operand)
                loaded = bool(re.match(r'\*\s*\(', stripped)) and not _binary_operators(stripped)
                if not (loaded or _compound(operand)) or re.fullmatch(r'\(?\s*[-+]?\d[\w.]*\s*\)?', operand):
                    continue
                for local, pointer in [(v, False) for v in integers] + [(v, True) for v in pointers if loaded]:
                    word = r'(?<![\w.>])' + local + r'\b'
                    if re.search(word, clean[start:stop]) or not _dead(clean, opening, end, blocks, loops, local, stop, start):
                        continue
                    stage = f'{local} = (void *) {operand};' if pointer else f'{local} = {operand};'
                    read = f'(u32) {local}' if pointer else local
                    text = f'{source[:start]}{stage} {source[start:a]}{read}{source[b:stop]}{source[stop:]}'
                    if (FAMILY, text) not in result:
                        result.append((FAMILY, text))
    return result


def _reuse_initialized_load(source, clean, opening, end, blocks, integers):
    """Reuse an untouched outer scalar for a short inner load lifetime before its next assignment."""
    body = clean[opening:end]
    if re.search(r"\b(?:volatile|asm|__asm__|goto)\b", clean) or re.search(r"^\s*#", source, re.M):
        return []
    results = []
    for begin, stop in blocks:
        if begin == opening or stop >= end:
            continue
        # A scalar halfword load followed only by pure scalar/constant initializers.
        head = re.match(r"\s*(s32|int)\s+(" + IDENT + r")\s*=\s*(\*\s*\(\s*u16\s*\*\s*\)\s*\(\s*" + IDENT + r"\s*\+\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)\s*\))\s*;", clean[begin+1:stop])
        if not head:
            continue
        old = head[2]
        start = begin + 1 + head.start()
        declaration_end = begin + 1 + head.end()
        insertion = declaration_end
        declaration = re.compile(r"\s*(?:s32|u32|int)\s+" + IDENT + r"\s*=\s*(?:" + IDENT + r"|(?:0[xX][0-9a-fA-F]+|[0-9]+))\s*;")
        while hit := declaration.match(clean, insertion, stop):
            insertion = hit.end()
        # Moving the load after declarations is safe only when those initializers
        # read plain locals, not globals, volatile objects, macros or calls.
        for initializer in re.finditer(r"=\s*(" + IDENT + r")\s*;", clean[declaration_end:insertion]):
            name = initializer[1]
            if not re.search(r"\b(?:s8|u8|s16|u16|s32|u32|int)\s+" + name + r"\b", clean[opening:start]):
                break
        else:
            name = None
        if name is not None:
            continue
        for local in integers:
            pattern = r"(?m)^\s*(?:register\s+)?(?:s32|int)\s+" + local + r"\s*;"
            prefix = clean[opening+1:start]
            declarations = list(re.finditer(pattern, prefix))
            if local == old or len(declarations) != 1:
                continue
            declared_at = opening + 1 + declarations[0].start()
            scope = _block_of(blocks, declared_at)
            if (not scope or not (scope[0] <= start < scope[1])
                    or len(re.findall(r"\b(?:s8|u8|s16|u16|s32|u32|int|char)\s+" + local + r"\b", body)) != 1):
                continue
            prefix = re.sub(pattern, "", prefix)
            if (re.search(r"(?<![\w.>])" + local + r"\b", prefix)
                    or re.search(r"(?<![\w.>])(?:" + old + "|" + local + r")\b",
                                 clean[declaration_end:insertion])
                    or re.search(r"(?<![\w.>])" + local + r"\b", head[3])):
                continue
            if re.search(r"&\s*" + local + r"\b|&\s*" + old + r"\b", body):
                continue
            after = clean[insertion:stop]
            overwrite = re.search(r"(?<![\w.>])" + local + r"\s*=\s*[^;{}]*;", after)
            if not overwrite:
                continue
            before = after[:overwrite.start()]
            tail = after[overwrite.end():]
            if (re.search(r"(?<![\w.>])" + local + r"\b", before)
                    or re.search(r"(?<![\w.>])" + old + r"\b", tail)
                    or not re.search(r"(?<![\w.>])" + old + r"\b", before)):
                continue
            # The overwrite cannot read the previous value; no macros or shadowing can alias it.
            if re.search(r"(?<![\w.>])" + local + r"\b", overwrite.group().split('=', 1)[1]):
                continue
            if len(re.findall(r"\b(?:s32|int|u32)\s+" + old + r"\b", body)) != 1:
                continue
            rewritten = re.sub(r"(?<![\w.>])" + old + r"\b", local, source[insertion:insertion+overwrite.end()])
            replacement = source[start:declaration_end].replace(source[start:declaration_end][head.start(3)-head.start():head.end(3)-head.start()], '', 1)
            # Replace the initializer with a declaration; retain the surrounding declaration text.
            replacement = re.sub(r"\s*=\s*;", ";", replacement)
            candidate = (source[:start] + replacement + source[declaration_end:insertion]
                         + "\n        " + local + " = " + source[start+head.start(3)-head.start():start+head.end(3)-head.start()] + ";"
                         + rewritten + source[insertion+overwrite.end():])
            results.append((FAMILY, candidate))
            if len(results) >= 4:
                return results
    return results
