"""Five spellings of one clamped colour-ramp loop that GCC 2.7.2 allocates differently, and the combination that pays off.

From a 168-instruction N64 menu function (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): a `do` loop over a table of
records whose body computes `alpha = 0xFF` or the ramp `0xFF - (-diff * 22)`, clamped, and stores
`(*flags & ~0xFF) | alpha` through the record. The saved best (340) was m2c's text; the target differs in four register
and order facts that no single edit moves (340 -> 330 -> 450 -> 350 -> 180 -> 60 -> 0 only as a set):
* the product `-diff * 22` is not masked to 16 bits (the mask m2c added turns the `bltz` into an `andi`) and is not a
  local of its own (the copy to a second register is the extra `move`): `product_inline`;
* the alpha is a halfword: a `u16` local is a different mode from the SImode constant 255, so cse does not give the
  `0xFF - x` its register and the constant is hoisted by loop.c as the target has it: `narrow_masked_local`
  (every use already says `& 0xFFFF`);
* the symbol's address is not kept in a local before the loop but written where the loop reads it, so loop.c hoists
  it in the order of use: `global_address_inline`;
* the order of the hoisted loop invariants decides which gets the lowest register (global.c ranks by live length,
  and a pseudo born earlier lives longer). A named constant set before the loop-entry copy is born first, which
  puts the 255 in the highest of the three registers as the target has it: `constant_local_before_copy`;
* a read-modify-write of a record field (`state->step += 6;`) followed by a load of a global is the target's load,
  load, add, store: `rmw_after_load`, with the load staying in the same block.
Every explanation is a hypothesis (sched.c, loop.c and global.c were not re-read for this); the measurement is that
the five together took the saved best from 340 to 0 and that each of the last two alone fixed two order rows.

Families:
* `product_inline` (and `product_unmasked_inline`, `product_mask_drop`), `narrow_masked_local`,
  `global_address_inline`, `constant_local_before_copy`, `rmw_after_load`: one edit each;
* `ramp_loop_combined`: every edit that applies, applied together, and the cumulative chains in that order (the
  edits are each no better alone).
Candidates for the exact judge, never a verdict."""
import re

from .integer_repair_support import IDENT, view

PRODUCT = 'product_inline'
UNMASKED = 'product_unmasked_inline'
MASK_DROP = 'product_mask_drop'
NARROW = 'narrow_masked_local'
ADDRESS = 'global_address_inline'
CONSTANT = 'constant_local_before_copy'
RMW = 'rmw_after_load'
COMBINED = 'ramp_loop_combined'
FAMILIES = (PRODUCT, UNMASKED, MASK_DROP, NARROW, ADDRESS, CONSTANT, RMW, COMBINED)
LIMIT = 14
WORD = r'(?<![\w.>]){}(?![\w])'
MASKS = {'0xFFFF': 'u16', '0xFF': 'u8'}


def _uses(text, name):
    return [m for m in re.finditer(WORD.format(re.escape(name)), text)]


def _assigned(text, name):
    return re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+\s*{re.escape(name)}\b|'
                     rf'\b{re.escape(name)}\s*\+\+', text)


def _parts(source, name):
    part = view(source, name)
    if not part:
        return None
    return source[:part.opening + 1], source[part.opening + 1:part.end - 1], source[part.end - 1:]


def _declaration(body, local, types=r'(?:s32|u32|int|unsigned int)'):
    return re.search(rf'(?m)^[ \t]*{types}\s+{re.escape(local)}\s*;[ \t]*\n', body)


def product(body):
    """[(family, body)]: a single-assignment integer local `t = EXPR;` read in two or more places, written as EXPR itself."""
    out = []
    for hit in re.finditer(rf'(?m)^(?P<indent>[ \t]*)(?P<v>{IDENT})\s*=\s*(?P<e>[^;\n{{}}]*\*[^;\n{{}}]*);[ \t]*\n', body):
        local, expr = hit['v'], hit['e'].strip()
        if not _declaration(body, local):
            continue
        rest = body[hit.end():]
        if len(_uses(body[:hit.start()], local)) != 1 or _assigned(rest, local) or len(_uses(rest, local)) < 2:
            continue
        names = {n for n in re.findall(IDENT, expr) if not n.isdigit()}
        if any(_assigned(rest, n) for n in names):
            continue
        masked = re.fullmatch(r'\(?(?P<inner>.*?)\)?\s*&\s*0xFFFF[uU]?', expr)
        plain = f"({masked['inner'].strip()})" if masked else None
        if masked:
            out.append((MASK_DROP, body[:hit.start('e')] + plain + body[hit.end('e'):]))
        for family, text in ((PRODUCT, f'({expr})'), (UNMASKED, plain)):
            if text is None:
                continue
            edited = body[:hit.start()] + re.sub(WORD.format(re.escape(local)), text.replace('\\', '\\\\'), rest)
            decl = _declaration(edited, local)
            out.append((family, edited[:decl.start()] + edited[decl.end():]))
    return out


def narrow_local(body):
    """[body]: an `s32` local whose every use says `& 0xFFFF` (or `& 0xFF`), declared as the narrow type."""
    out = []
    for hit in re.finditer(r'(?m)^(?P<indent>[ \t]*)(?:s32|int|u32)\s+(?P<v>' + IDENT + r')\s*;', body):
        local = hit['v']
        uses = [m for m in _uses(body, local) if m.start() != hit.start('v')]
        masked = [m for m in uses if re.match(r'\s*\)?\s*&\s*(0xFFFF|0xFF)\b', body[m.end():])]
        writes = [m for m in uses if re.match(r'\s*=(?!=)', body[m.end():])]
        if not masked or len(masked) + len(writes) != len(uses):
            continue
        kinds = {re.match(r'\s*\)?\s*&\s*(0xFFFF|0xFF)', body[m.end():])[1] for m in masked}
        if len(kinds) != 1:
            continue
        out.append(body[:hit.start()] + f"{hit['indent']}{MASKS[kinds.pop()]} {local};" + body[hit.end():])
    return out


def address_local(body):
    """[body]: `T *p = &sym;` read only as `*p`, written as the read through the symbol where it is used."""
    out = []
    for hit in re.finditer(rf'(?m)^[ \t]*(?P<t>{IDENT}(?:\s+{IDENT})?)\s*\*\s*(?P<v>{IDENT})\s*=\s*&\s*(?P<sym>{IDENT})\s*;[ \t]*\n', body):
        local, symbol, kind = hit['v'], hit['sym'], hit['t']
        rest = body[hit.end():]
        uses = _uses(rest, local)
        if not uses or _assigned(rest, local) or _assigned(rest, symbol) or _uses(body[:hit.start()], local):
            continue
        if any(not re.search(r'\*\s*$', rest[max(0, m.start() - 4):m.start()]) for m in uses):
            continue
        text = re.sub(rf'\*\s*{re.escape(local)}\b', f'*({kind} *)((char *)&{symbol})', rest)
        out.append(body[:hit.start()] + text)
    return out


def constant_local(body):
    """[body]: `0xFF - x` inside a `do` loop as `k - x` with `k = 0xFF` set before the loop's entry copies."""
    out = []
    for loop in re.finditer(r'(?m)^(?P<indent>[ \t]*)do\s*\n?[ \t]*\{', body):
        end = body.find('while', loop.end())
        if end < 0:
            continue
        for use in re.finditer(r'(?<![\w.>])(?P<c>0x[0-9A-Fa-f]{2,4}|[1-9][0-9]{2,4})\s*-\s*(?=[\w(])', body[loop.end():end]):
            lines = body[:loop.start()].rstrip('\n').split('\n')
            first = len(lines)
            while first and re.match(rf'\s*{IDENT}(?:\s+{IDENT})?\s*\**\s*{IDENT}\s*=\s*[^;]*;\s*$', lines[first - 1]):
                first -= 1
            if first == len(lines):
                continue
            const = use['c']
            name = 'k' + re.sub(r'\W', '', const)
            at = len('\n'.join(lines[:first])) + (1 if first else 0)
            where = loop.end() + use.start()
            if re.search(WORD.format(name), body):
                continue
            indent = re.match(r'[ \t]*', lines[first]).group()
            text = body[:at] + f'{indent}s32 {name} = {const};\n' + body[at:where] + name + body[where + len(const):]
            out.append(text)
            break
    return out


def rmw_after_load(body):
    """[body]: `*(T *)(a) += k;` then `do { x = G; ... } while (0);` as the load, then the store, in one block."""
    out = []
    for hit in re.finditer(rf'(?m)^(?P<indent>[ \t]*)(?P<lhs>\*\(\((?P<t>u8|s8|u16|s16|u32|s32) \*\)[^;\n]*?\))\s*\+=\s*(?P<k>[^;\n]+);[ \t]*\n'
                           rf'(?P<fence>[ \t]*do\s*\n?[ \t]*\{{\s*(?P<load>{IDENT}\s*=\s*{IDENT}\s*;)\s*(?P<rest>[^{{}}]*?)\}}\s*while\s*\(\s*0\s*\)\s*;[ \t]*\n)', body):
        indent, lhs, kind = hit['indent'], hit['lhs'], hit['t']
        t = 'rmwOld'
        if re.search(WORD.format(t), body):
            continue
        rest = hit['rest'].strip()
        fence = f'{indent}do {{ {rest} }} while (0);\n' if rest else ''
        block = (f'{indent}{{ {kind} {t} = {lhs};\n{indent}{hit["load"]}\n{indent}{lhs} = {t} + {hit["k"]};\n{fence}{indent}}}\n')
        out.append(body[:hit.start()] + block + body[hit.end():])
    return out


STEPS = ((UNMASKED, lambda b: [x for f, x in product(b) if f == UNMASKED][:1]),
         (NARROW, lambda b: narrow_local(b)[:1]),
         (ADDRESS, lambda b: address_local(b)[:1]),
         (RMW, lambda b: rmw_after_load(b)[:1]),
         (CONSTANT, lambda b: constant_local(b)[:1]))


def variants(source, name):
    pieces = _parts(source, name)
    if not pieces:
        return []
    head, body, tail = pieces
    out = []
    for family, text in product(body):
        out.append((family, head + text + tail))
    out.extend((NARROW, head + text + tail) for text in narrow_local(body))
    out.extend((ADDRESS, head + text + tail) for text in address_local(body))
    out.extend((CONSTANT, head + text + tail) for text in constant_local(body))
    out.extend((RMW, head + text + tail) for text in rmw_after_load(body))
    # the edits are each no better alone: the cumulative chains, then all of them
    current, applied = body, 0
    for _family, step in STEPS:
        found = step(current)
        if found:
            current, applied = found[0], applied + 1
            if applied > 1:
                out.append((COMBINED, head + current + tail))
    return out[:LIMIT + 6]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 94}  # the registry: no caller wiring (registry.py)
