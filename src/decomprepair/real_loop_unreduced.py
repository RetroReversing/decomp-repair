"""A table loop the target compiled without strength reduction, written as the real loop it was (KMC GCC 2.7.2).

m2c writes a counted loop as `L: { ... } if (i < n) goto L;` and a table store as `*(T *)(SYM + idx * K) = v;`.
Three facts about `gcc-2.7.2-kmc -O2` decide whether such a function can match, and none of them shows in the
diff as a source edit alone:

* A loop written with a backward `goto` has no `NOTE_INSN_LOOP_BEG`, so flow.c weights every reference at depth 1 and
  loop.c never looks at it. Written as `do { } while (c)` the references inside count with the loop's depth
  (`reg_n_refs += loop_depth`), which changes global.c's priority order of the saved registers: in one 132-instruction
  function the offset, counter, last-index and base-pointer registers were all rotated by the goto form and all in the
  target's order as a `do`/`while`, with no `do { } while (0)` ladders (a hypothesis read from flow.c and global.c; the
  register figures are the evidence).
* Under the real loop, loop.c hoists the table symbol's address (`la`) out of the loop when it is a separate set, and
  cse2 can no longer fold it into the store's `lui $at; addu $at,$at,idx; sw %lo($at)` address. Writing the address
  into a pointer local first (`{ T *q; q = (T *)(SYM + idx * K); *q = v; }`) keeps it one set that stays in place.
* The `lui $at; addu $at,$at,reg` table idiom in the target is the signature of `-fno-strength-reduce`, so the profile
  has to change with the source: neither alone moves the score (the real loop under the old profile scored 4924).

`variants` offers the two source steps as families; `probes` offers the whole joint child (loop, entry guard of the
counter compare, store pointer) with the profile that goes with it, for the preflight's profile probes.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

LOOP = 'goto_label_do_while'
STORE = 'symbol_store_pointer_local'
FAMILIES = (LOOP, STORE)
FLAG = '-fno-strength-reduce'
TYPE = r'(?:(?:unsigned|signed)\s+)?(?:char|short|int|long)|[su](?:8|16|32|64)|f32'
TABLE_IDIOM = re.compile(r'lui\s+\$at\b[^\n]*\n[^\n]*?\baddu\s+\$at,\s*\$at', re.I)  # a listing's address comments may lead each line


def _loops(source, name):
    """`[(start, end, replacement)]` for each `L: {body} if (c) goto L;` (or `L: body if (c) goto L;`) of the function."""
    part = view(source, name)
    if not part:
        return []
    clean, edits = part.clean, []
    for found in re.finditer(rf'\bgoto\s+(?P<label>{IDENT})\s*;', clean[part.opening:part.end]):
        label = found['label']
        gstart = part.opening + found.start()
        if len(re.findall(rf'\bgoto\s+{re.escape(label)}\s*;', clean[part.opening:part.end])) != 1:
            continue
        # the guard `if (cond)` directly before the goto
        head = clean[part.opening:gstart].rstrip()
        if not head.endswith(')'):
            continue
        depth, i = 0, len(head) - 1
        while i >= 0:
            depth += (head[i] == ')') - (head[i] == '(')
            if depth == 0:
                break
            i -= 1
        guard = re.search(r'\bif\s*$', head[:i])
        if i < 0 or not guard:
            continue
        if_at = part.opening + guard.start()
        definition = re.search(rf'(?<![\w?:])\b{re.escape(label)}\s*:(?!:)', clean[part.opening:if_at])
        if not definition:
            continue
        lstart = part.opening + definition.start()
        body = clean[part.opening + definition.end():if_at]
        if re.search(r'\b(?:continue|break|switch|case|default)\b', body) or body.count('{') != body.count('}'):
            continue
        original = source[part.opening + definition.end():if_at]
        original = original.strip()
        braced = body.strip()
        if braced.startswith('{') and close(braced, 0, '{', '}') == len(braced):
            original = original[1:-1]
        written = source[part.opening + i + 1:part.opening + len(head) - 1].strip()
        edits.append((lstart, part.opening + found.end(), f'do {{{original}}} while ({written});'))
    return edits


def loop_variants(source, name):
    result = []
    part = view(source, name)
    if not part:
        return result
    for start, end, text in _loops(source, name):
        child = edit(source, [(start, end, text)])
        if child != source and child not in result:
            result.append(child)
    return result


EXTERN_ARRAY = re.compile(rf'\bextern\s+[\w\s\*]*?\b(?P<name>{IDENT})\s*\[\s*\]\s*;')
STORE_STATEMENT = re.compile(
    rf'(?P<lead>[;{{}}]\s*)\*\s*\(\s*(?P<type>{TYPE})\s*\*\s*\)\s*\(\s*(?P<sym>{IDENT})\s*\+\s*(?P<index>[^;=]+?)\s*\)'
    rf'\s*=\s*(?P<value>[^;]+);')


def store_variants(source, name):
    part = view(source, name)
    if not part:
        return []
    arrays = set(EXTERN_ARRAY.findall(part.clean[:part.opening]))
    result = []
    for found in STORE_STATEMENT.finditer(part.clean, part.opening, part.end):
        if found['sym'] not in arrays:
            continue
        s, e = found.start() + len(found['lead']), found.end()
        pointer = 'store_ptr'
        if re.search(rf'\b{pointer}\b', part.clean):
            continue
        text = (f"{{ {found['type']} *{pointer}; {pointer} = ({found['type']} *)({found['sym']} + "
                f"{source[found.start('index'):found.end('index')]}); *{pointer} = "
                f"{source[found.start('value'):found.end('value')]}; }}")
        child = edit(source, [(s, e, text)])
        if child not in result:
            result.append(child)
        if len(result) >= 4:
            break
    return result


def strip_weight_ladders(source, name):
    """Every `do { S } while (0);` scope of the function written as `S`: the saved best's weight ladders were found
    under the goto loop's depth-1 weights and fight the real loop's (they are put back by the ladder families if the
    profile wants them)."""
    part = view(source, name)
    if not part:
        return source
    text = source
    for _ in range(12):
        part = view(text, name)
        found = None
        for start in (m.start() for m in re.finditer(r'\bdo\s*\{', part.clean[part.opening:part.end])):
            at = part.opening + start
            brace = part.clean.index('{', at)
            stop = close(part.clean, brace, '{', '}')
            tail = re.match(r'\s*while\s*\(\s*0\s*\)\s*;', part.clean[stop:part.end]) if stop else None
            if tail:
                found = (at, stop + tail.end(), text[brace + 1:stop - 1].strip())
                break
        if not found:
            break
        text = edit(text, [found])
    return text


def variants(source, name, header=''):
    return ([(LOOP, text) for text in loop_variants(source, name)]
            + [(STORE, text) for text in store_variants(source, name)])


def probes(proj, fn, own, header=''):
    """The real loop, the counter-compare entry guard and the store pointer, with `-fno-strength-reduce`."""
    if dict(proj).get('arch') != 'mips' or own.get('toolchain') != 'gcc-2.7.2-kmc':
        return []
    flags = own['flags'].split() if isinstance(own['flags'], str) else list(own['flags'])
    source, name, asm = fn['best_source'], fn['name'], dict(fn).get('asm') or ''
    if FLAG in flags or not source or not TABLE_IDIOM.search(asm):
        return []
    looped = loop_variants(strip_weight_ladders(source, name), name)
    if not looped:
        return []
    child = looped[0]
    from .loop_guard_counter_compare import variants as guards
    child = next((text for _, text in guards(child, name) if text != child), child)
    child = next(iter(store_variants(child, name)), child)
    return [([*flags, FLAG], child)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
