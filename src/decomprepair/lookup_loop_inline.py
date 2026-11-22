"""A table search that m2c unrolled into goto spaghetti, written once as an inline helper and called where it was.

A function that searches the same table several times (a slot lookup by id: a busy byte and a key word at a stride,
the count and the stride stepped together, a flag bit carried from the id into the result) comes out of m2c as one
copy of the loop per search, each with its own counter, stride and key variables, a `found_N:` stub that is jumped to
from the loop and jumped out of again, a `join_N:` label, and a chain of `goto skip_N;` that hops over the stubs:

    var_a0 = 0; temp_a1 = X; temp_v0 = temp_a1 & 0x7FFFFFFF; var_v1 = 0;
    loop_N: if ((busy[var_v1] != 0) || (key[var_v1] != temp_v0)) {
                var_a0 += 1; var_v1 += 0xFF8;
                if (var_a0 >= 8U) { res = -1; } else { goto loop_N; }
            } else { goto found_N; }
    join_N: slot = res; if (slot != -1) { ... }     found_N: res = var_a0 | (temp_a1 & 0x80000000); goto join_N;

The game's source had one `static inline` helper called at each search, whose caller wrote `id = find(id)` and read
the index from the same variable. GCC 2.7.2 (KMC, N64) expands an inline call into pseudo registers of its own: the
parameter, counter, key and offset are new pseudos at every expansion, so each search is allocated by its own short
live ranges. With m2c's copies the id and the slot are locals shared by every search in the function, one long-lived
pseudo that outranks the counters and takes `$a0` in every region, where the target has the counter in `$a0` and the
id and slot in `$a1`. The helper's body is the loop as the sibling functions that matched wrote it:

    static inline s32 find_entry(s32 id) {
        u32 i = 0; s32 key = id & 0x7FFFFFFF; s32 off = 0;
        for (; i < 8; i++, off += 0xFF8) {
            if (busy[off] == 0 && key[off] == key) { return i | (id & 0x80000000); }
        }
        return -1;
    }

Children: every search (two or more with the same table, stride, limit and element types) replaced by
`res = find_entry(id);`, with the stub, the join label, the counter/stride/key setup and the jumps that only hopped
over the stubs removed (`lookup_loop_inline`); and that with each search's id and slot (the `temp = EXPR;
res = find_entry(temp); slot = res; if (slot != -1) {..}` run, when nothing reads either afterwards) as one local of its
own, declared in the block that holds the run (`lookup_loop_inline_private`). A sound-entity function of 588
instructions (KMC GCC 2.7.2, saved best 190) needed both together: the helper alone is 350 (instructions identical,
70 register rows), the combination 20 (the four rows of a halfword/word pair's saved registers), and `arm_scoped_scratch`
then gives 0. A search that only pays off combined is why the second child is its own family. Only MIPS; the candidate
is never a verdict: the judge decides. The rewrite keeps the meaning: the same loop, the same tests in the same order,
the same value out.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

HELPER = 'lookup_loop_inline'
PRIVATE = 'lookup_loop_inline_private'
FAMILIES = (HELPER, PRIVATE)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_TYPE = r'(?:u8|s8|u16|s16|u32|s32)'

_BUSY = (rf'\(\s*\*\s*\(\s*(?P<btype>{_TYPE})\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*\(\s*&\s*(?P<busy>{_ID})\s*\)\s*\+\s*'
         rf'(?P<v>{_ID})\s*\)\s*\)\s*!=\s*0')
_TABLE = (rf'\(\s*\*\s*\(\s*(?P<ttype>{_TYPE})\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*\(\s*&\s*(?P<tab>{_ID})\s*\)\s*\+\s*'
          rf'(?P=v)\s*\)\s*\)\s*!=\s*(?P<key>{_ID})')
_STEP = (rf'(?P<cnt>{_ID})\s*\+=\s*1\s*;\s*(?P=v)\s*\+=\s*(?P<stride>{_NUM})\s*;\s*'
         rf'if\s*\(\s*(?:(?P=cnt)\s*>=\s*(?P<lim1>{_NUM})U?|(?P<lim2>{_NUM})U?\s*<=\s*(?P=cnt))\s*\)\s*\{{\s*'
         rf'(?P<res>{_ID})\s*=\s*-1\s*;\s*\}}\s*else\s*\{{\s*')
_TEST = rf'if\s*\(\s*\(\s*{_BUSY}\s*\)\s*\|\|\s*\(\s*{_TABLE}\s*\)\s*\)\s*\{{\s*'
# the loop as `label: if (...) { ...; if (...) { res = -1; } else { goto label; } } else { goto found; }`
_LABELLED = re.compile(rf'(?P<label>{_ID})\s*:\s*{_TEST}{_STEP}goto\s+(?P=label)\s*;\s*\}}\s*\}}\s*else\s*\{{\s*goto\s+'
                       rf'(?P<found>{_ID})\s*;\s*\}}')
# ... or `for (;;) { if (...) { ...; if (...) { res = -1; } else { continue; } } else { goto found; } break; }`
_FOR = re.compile(rf'for\s*\(\s*;\s*;\s*\)\s*\{{\s*{_TEST}{_STEP}continue\s*;\s*\}}\s*\}}\s*else\s*\{{\s*goto\s+'
                  rf'(?P<found>{_ID})\s*;\s*\}}\s*break\s*;\s*\}}')


def _stub(found):
    return re.compile(rf'(?P<label>\b{found})\s*:\s*(?P<res>{_ID})\s*=\s*(?P<cnt>{_ID})\s*\|\s*\(\s*(?P<id>{_ID})\s*&\s*'
                      rf'0[xX]80000000\s*\)\s*;\s*goto\s+(?P<join>{_ID})\s*;[ \t]*\n?')


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        if not text and source[end - 1:end] == '\n':  # a deleted statement that filled its line takes the indent too
            while start > 0 and source[start - 1] in ' \t':
                start -= 1
        source = source[:start] + text + source[end:]
    return source


def _words(clean, name):
    return [m.start() for m in re.finditer(rf'(?<![\w.]){re.escape(name)}\b', clean)]


def _sites(clean, start, end):
    """Every search loop in [start, end): (match, form, signature) in source order."""
    found = []
    for form, pattern in (('label', _LABELLED), ('for', _FOR)):
        for m in pattern.finditer(clean, start, end):
            lim = m['lim1'] or m['lim2']
            signature = (m['btype'], m['busy'], m['ttype'], m['tab'], m['stride'], lim)
            found.append((m, form, signature))
    found.sort(key=lambda item: item[0].start())
    return found


def _helper(name, signature):
    btype, busy, ttype, tab, stride, limit = signature
    return (f'static inline s32 {name}(s32 id) {{\n'
            f'    u32 i = 0;\n'
            f'    s32 key = id & 0x7FFFFFFF;\n'
            f'    s32 off = 0;\n\n'
            f'    for (; i < {limit}; i++, off += {stride}) {{\n'
            f'        if (*({btype} *)((char *)(&{busy}) + off) == 0 && '
            f'*({ttype} *)((char *)(&{tab}) + off) == key) {{\n'
            f'            return i | (id & 0x80000000);\n'
            f'        }}\n'
            f'    }}\n'
            f'    return -1;\n'
            f'}}\n\n')


def _cleanup(source, start):
    """Drop `goto L;` that is followed straight by `L:`, then every label nothing jumps to. `start`: the function."""
    for _ in range(40):
        clean = _blank(source)
        changed = False
        for m in re.finditer(rf'goto\s+(?P<label>{_ID})\s*;\s*(?P=label)\s*:', clean[start:]):
            source = source[:start + m.start()] + source[start + m.end() - len(m['label']) - 1:]
            changed = True
            break
        if changed:
            continue
        for m in re.finditer(rf'(?m)^[ \t]*(?P<label>{_ID})[ \t]*:(?!:)', clean[start:]):
            label = m['label']
            if label in ('default', 'case') or re.search(rf'\bgoto\s+{label}\b', clean[start:]):
                continue
            if re.search(rf'\b(?:case|default)\b[^:\n]*\b{label}\s*:', clean[start + m.start():start + m.end()]):
                continue
            # only labels this rewrite could have orphaned: the search's own and m2c's hop targets
            if not re.match(r'(?:loop|found|join|skip|have|negative|handle|setup|[A-Za-z_]+_\d+)', label):
                continue
            line = start + m.start()
            end = start + m.end()
            tail = re.match(r'[ \t]*\n', source[end:])
            if tail:  # the label stood alone on its line: drop the line
                source = source[:line] + source[end + tail.end():]
            else:
                source = source[:start + m.start('label')] + source[end:].lstrip(' \t')
            changed = True
            break
        if not changed:
            break
    return source


def _decl(source, clean, name):
    """The declaration statement of a local `name` (its own line), or None."""
    return re.search(rf'(?m)^[ \t]*(?:register\s+)?(?:unsigned\s+(?:int\s+)?|{_TYPE}\s+|int\s+|long\s+)[\w\s\*]*?\b{name}\s*;[ \t]*\n',
                     clean)


def _rewrite(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0 or re.search(r'\bvolatile\b', clean[span[0]:span[1]]):
        return None
    groups = {}
    for site in _sites(clean, opening, span[1]):
        groups.setdefault(site[2], []).append(site)
    group = max(groups.values(), key=len, default=[])
    if len(group) < 2:
        return None
    helper_name = 'find_entry'
    while re.search(rf'\b{helper_name}\b', clean):
        helper_name += '_'
    edits, touched = [], set()
    for site, _, _ in group:
        made = _site_edits(clean, opening, span, site, helper_name)
        if made is None:
            return None
        edits.extend(made)
        touched.update({site['cnt'], site['v'], site['key'], site['res'], _stub(site['found']).search(clean)['id']})
    result = _apply(source, edits)
    start, end = find(result, name)
    result = _cleanup(result, start)
    start, end = find(result, name)
    clean = _blank(result)
    drop = []
    for var in sorted(touched):
        if len(_words(clean[start:end], var)) == 1:
            decl = _decl(result, clean[start:end], var)
            if decl:
                drop.append((start + decl.start(), start + decl.end(), ''))
    result = _apply(result, drop)
    start = find(result, name)[0]
    return result[:start] + _helper(helper_name, group[0][2]) + result[start:]


def _site_edits(clean, opening, span, site, helper_name):
    """The edits that turn one search loop into a call, or None when its pieces are not where m2c puts them."""
    stub = _stub(site['found']).search(clean, opening, span[1])
    if not stub or stub['cnt'] != site['cnt'] or stub['res'] != site['res']:
        return None
    ident, loop_start, loop_end = stub['id'], site.start(), site.end()
    edits = []
    # the setup statements: `cnt = 0;`, `v = 0;` and `key = id & 0x7FFFFFFF;`, the last of each before the loop
    for pattern in (rf'(?<![\w.]){site["cnt"]}\s*=\s*0\s*;[ \t]*\n?',
                    rf'(?<![\w.]){site["v"]}\s*=\s*0\s*;[ \t]*\n?',
                    rf'(?<![\w.]){site["key"]}\s*=\s*{ident}\s*&\s*0[xX]7[Ff]{{7}}\s*;[ \t]*\n?'):
        last = None
        for m in re.finditer(pattern, clean[opening:loop_start]):
            last = m
        if not last:
            return None
        edits.append((opening + last.start(), opening + last.end(), ''))
    edits.append((stub.start(), stub.end(), ''))
    join = re.search(rf'(?<![\w.]){stub["join"]}\s*:[ \t]*\n?', clean[opening:span[1]])
    if join:
        edits.append((opening + join.start(), opening + join.end(), ''))
    # a loop that began at column 0 (m2c's label) takes the indent of the line after it
    prefix = clean[clean.rfind('\n', 0, loop_start) + 1:loop_start]
    after = re.match(r'[^\n]*\n(?:[ \t]*\n)*([ \t]*)', clean[loop_end:])
    lead = after[1] if after and not prefix else ''
    edits.append((loop_start, loop_end, f'{lead}{site["res"]} = {helper_name}({ident});'))
    return edits


def _enclosing(clean, at, floor):
    """(open, close) of the innermost `{ }` around `at`, or None at function level."""
    depth, pos = 0, at
    while pos > floor:
        pos -= 1
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                end = close(clean, pos, '{', '}')
                return (pos, end) if end else None
            depth -= 1
    return None


def _statement_end(clean, pos):
    """The position just past the statement that starts at `pos` (an `if` chain or a simple statement), or None."""
    m = re.compile(r'\s*').match(clean, pos)
    pos = m.end()
    if re.match(r'if\b', clean[pos:pos + 3]):
        opening = clean.find('(', pos)
        end = close(clean, opening) if opening >= 0 else None
        while end:
            end = re.compile(r'\s*').match(clean, end).end()
            if clean[end:end + 1] != '{':
                nxt = clean.find(';', end)
                end = nxt + 1 if nxt >= 0 else None
            else:
                end = close(clean, end, '{', '}')
            if not end:
                return None
            more = re.compile(r'\s*else\b\s*').match(clean, end)
            if not more:
                return end
            end = more.end()
            if re.match(r'if\b', clean[end:end + 3]):
                opening = clean.find('(', end)
                end = close(clean, opening) if opening >= 0 else None
        return end
    semi = clean.find(';', pos)
    return semi + 1 if semi >= 0 else None


def _declared(clean, name):
    m = re.search(rf'(?m)^[ \t]*(?P<type>(?:register\s+)?[A-Za-z_][\w ]*?)\s+{name}\s*;', clean)
    return re.sub(r'\s+', ' ', m['type']).replace('register ', '').strip() if m else None


def _private(source, name, helper_name):
    """The result of `res = find(id); slot = res; if (slot != -1) {...}` as one local of its own per search, as the
    inline helper's parameter was: the id loaded into it, the index written back into it, the block that reads it."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', *span)
    body_end = span[1]
    taken = set()
    edits = []
    call = re.compile(rf'(?P<res>{_ID})\s*=\s*{helper_name}\s*\(\s*(?P<id>{_ID})\s*\)\s*;')
    for m in call.finditer(clean, opening, body_end):
        res, ident = m['res'], m['id']
        copy = re.compile(rf'\s*(?P<x>{_ID})\s*=\s*{res}\s*;').match(clean, m.end())
        if not copy:
            continue
        slot = copy['x']
        end = _statement_end(clean, copy.end())
        assign = None
        for a in re.finditer(rf'(?<![\w.]){ident}\s*=\s*(?P<expr>[^;{{}}=][^;{{}}]*);', clean[opening:m.start()]):
            assign = a
        if not end or not assign:
            continue
        first = opening + assign.start()
        if re.search(rf'(?<![\w.]){ident}\b', clean[opening + assign.end():m.start()]):
            continue
        kind = _declared(clean[opening:body_end], ident)
        if kind is None or kind != _declared(clean[opening:body_end], slot):
            continue
        block = _enclosing(clean, first, opening)
        if block and end > block[1]:
            continue
        # the id is read by the call only, the slot is not touched before its copy, and neither is read after the
        # block until it is written again
        bad = ident != slot and re.search(rf'(?<![\w.]){slot}\b', clean[first:m.end()])
        checks = [(slot, clean[end:body_end])]
        if ident != slot:
            checks.append((ident, clean[m.end():body_end]))
        for var, rest in checks:
            nxt = re.search(rf'(?<![\w.]){var}\s*=[^=]', rest)
            if re.search(rf'(?<![\w.]){var}\b', rest[:nxt.start() if nxt else len(rest)]):
                bad = True
        if bad:
            continue
        fresh = f'{slot}_p'
        while fresh in taken or re.search(rf'\b{fresh}\b', clean):
            fresh += '_'
        taken.add(fresh)
        regions = [(first, m.end(), ident), (copy.start(), end, slot)]
        for lo, hi, var in regions:
            for hit in re.finditer(rf'(?<![\w.>]){var}\b(?!\s*:(?!:))', clean[lo:hi]):
                edits.append((lo + hit.start(), lo + hit.end(), fresh))
        if block:
            at = block[0] + 1
            following = re.compile(r'\s*').match(clean, at).end()
            indent = ' ' * (following - (clean.rfind('\n', 0, following) + 1))
            edits.append((at, at, f'\n{indent}{kind} {fresh};'))
        else:
            edits.append((opening + 1, opening + 1, f'\n    {kind} {fresh};'))
    if not edits:
        return None
    return _apply(source, edits)


def variants(source, name):
    """The searches as one inline helper (`lookup_loop_inline`), and that with each search's id and slot as a local of
    its own (`lookup_loop_inline_private`: the match needs both; the first alone is worse than the saved best)."""
    helper = _rewrite(source, name)
    if not helper or helper == source:
        return []
    out = [(HELPER, helper)]
    name_ = re.search(r'static inline s32 (\w+)\(s32 id\)', helper)[1]
    private = _private(helper, name, name_)
    if private and private != helper:
        out.append((PRIVATE, private))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
