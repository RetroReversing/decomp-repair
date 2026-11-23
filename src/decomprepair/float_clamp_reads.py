"""Two float spellings m2c gives a clamp of fields, written back with the reads where the game had them.

Found on a 1300-instruction KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) controller routine (550 -> 500 with both,
530 with the first alone: the second only pays off with it).

min_clamp_field_reads
    `t = A; if (t < B) { B = t; }` (A and B field or global reads, t a float local read nowhere else) written
    `if (B > A) { B = A; }`: the target loads B first (`lwc1 $f0, 0x40; lwc1 $f2, 0x44; c.lt.s $f2, $f0`), where m2c's
    order loads A into t first.

product_store_retarget
    `v = X * v; F = v;` (v a float local multiplied in place and stored at once, X a read) with the rest of the block
    reading the product: the product goes to a new local instead (`p = X * v; F = p; .. p ..`). Written back into `v`,
    expand_binop makes `v` the destination and first operand, so the product shares `v`'s register (`mul.s $f20,
    $f20, $f0`); the target multiplies into a temporary (`mul.s $f0, $f0, $f24`) and keeps the scale in its own
    register. Offered only when v is not read after the block.

Read off the target's instructions and `-dl -dg` tables; hypotheses, not confirmed in the compiler's source."""
import re

from .csource import _blank, find

FAMILY_MIN = 'min_clamp_field_reads'
FAMILY_PRODUCT = 'product_store_retarget'
FAMILIES = (FAMILY_MIN, FAMILY_PRODUCT)
LIMIT = 8
IDENT = r'[A-Za-z_]\w*'
READ = (r'(?:\(\s*\(\s*\w+\s*\*\s*\)\s*\(\s*\(\s*\(\s*char\s*\*\s*\)\s*\w+\s*\)\s*\+\s*0[xX][0-9a-fA-F]+\s*\)\s*\)\s*->\s*\w+'
        r'|\w+\s*->\s*\w+|[A-Z]\w*)')


def _span(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    return (span[0] + head.end() - 1, span[1]) if head else None


def _mention(name):
    return re.compile(rf'(?<![\w.>]){re.escape(name)}\b')


def _floats(body):
    return set(re.findall(rf'^[ \t]*(?:f32|float)[ \t]+({IDENT})[ \t]*;', body, re.M))


def _close(text, at):
    depth = 0
    for index in range(at, len(text)):
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
            if depth < 0:
                return index
    return None


def _min_clamps(source, span):
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    floats = _floats(body)
    shape = re.compile(rf'^(?P<i>[ \t]*)(?P<t>{IDENT})\s*=\s*(?P<a>{READ})\s*;[ \t]*\n'
                       rf'[ \t]*if\s*\(\s*(?P=t)\s*<\s*(?P<b>{READ})\s*\)\s*\n?[ \t]*\{{\s*(?P=b)\s*=\s*(?P=t)\s*;\s*\}}[ \t]*\n', re.M)
    out = []
    for hit in shape.finditer(clean, span[0], span[1]):
        t, a, b = hit['t'], source[hit.start('a'):hit.end('a')].strip(), source[hit.start('b'):hit.end('b')].strip()
        if t not in floats or len(_mention(t).findall(body)) != 4:  # its declaration and the three here
            continue
        i = hit['i']
        text = f'{i}if ({b} > {a})\n{i}{{\n{i}  {b} = {a};\n{i}}}\n'
        child = source[:hit.start()] + text + source[hit.end():]
        child = re.sub(rf'^[ \t]*(?:f32|float)[ \t]+{re.escape(t)}[ \t]*;[ \t]*\n', '', child, count=1, flags=re.M)
        out.append((FAMILY_MIN, child))
    return out


def _products(source, span):
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    floats = _floats(body)
    shape = re.compile(rf'^(?P<i>[ \t]*)(?P<v>{IDENT})\s*=\s*(?P<x>{READ})\s*\*\s*(?P=v)\s*;[ \t]*\n'
                       rf'(?P<store>[ \t]*(?P<f>{READ})\s*=\s*(?P=v)\s*;[ \t]*\n)', re.M)
    out = []
    used = set(re.findall(IDENT, body))
    for hit in shape.finditer(clean, span[0], span[1]):
        v = hit['v']
        if v not in floats:
            continue
        stop = _close(clean, hit.end())
        if stop is None:
            continue
        mention = _mention(v)
        later = mention.search(clean, stop, span[1])
        if later and not re.match(rf'{re.escape(v)}\s*=(?!=)', clean[later.start():]):
            continue
        fresh = next(f'product_{n}' if n else 'product' for n in range(100) if (f'product_{n}' if n else 'product') not in used)
        edits = [(hit.start('v'), hit.end('v'), fresh)]
        for m in mention.finditer(clean, hit.start('store'), stop):
            edits.append((m.start(), m.end(), fresh))
        child = source
        for start, end, text in sorted(edits, reverse=True):
            child = child[:start] + text + child[end:]
        decl = re.search(rf'^([ \t]*)(?:f32|float)[ \t]+{re.escape(v)}[ \t]*;[ \t]*\n', child[span[0]:], re.M)
        at = span[0] + decl.end()
        child = child[:at] + f'{decl[1]}f32 {fresh};\n' + child[at:]
        out.append((FAMILY_PRODUCT, child))
    return out


def variants(source, name):
    span = _span(source, name)
    if not span:
        return []
    mins, products = _min_clamps(source, span), _products(source, span)
    out = []
    if mins and products:
        # the two together first: in the routine above the product alone was worse (555) and with the clamp 500
        both = mins[0][1]
        again = _span(both, name)
        if again:
            more = _products(both, again)
            if more:
                out.append((FAMILY_PRODUCT, more[0][1]))
    out += mins + products
    seen, unique = set(), []
    for family, child in out:
        if child != source and child not in seen:
            seen.add(child)
            unique.append((family, child))
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
