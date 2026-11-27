"""Edits that only pay off together: loop-depth weights, a spilled stack local used directly, and an init sunk into its guard.

GCC 2.x counts every reference to a pseudo once per loop depth (flow.c) and global.c hands the saved registers out by
`floor_log2(uses) * uses / live_length` (hypothesis, from the dumps of one function). Four edits changed that
function from 80 to 65 and none of them scored under 80 alone (alone: 1596, 320, 160, 80; together 65; the pairs and
triples in between 115 to 1675), so the permuter's one-edit-at-a-time search could not see them:

- `spill_slot_copy_collapse` (D): m2c writes a pointer chain through a temporary and copies it once into a stack local
  (`temp = &base[n]; next = &temp[n]; ...; slot = temp;`, `slot` read later). Written through `slot` itself, the stack
  local is the spilled pseudo, and reload picks its first free reload register ($t0) for the chain's first add
  instead of local-alloc's $a3. Not offered when either name is stepped (`+=`, `++`): a cursor reset from the base on
  every outer iteration would lose its reset.
- `weight_scope_unwrap` (U, I): a `do { ... } while (0);` is still a loop when references are counted, so everything
  inside counts double. The existing `one_shot_scope` skips a wrapper whose body holds a label or `goto`, so the
  function-body wrapper that holds m2c's `block_N:` labels was never unwrapped. A wrapper whose gotos and labels all
  lie inside it (and with no break/continue or declaration) becomes a plain block. U is the wrapper around the whole
  body, I every inner wrapper around one call.
- `init_sink_into_guard` (S): `v = K;` right before `if (c) {` moves to the start of that block when `c` does not
  read `v` (the first scheduler region and the delay slot choice follow it); each site is a child, and all at once.
- `weight_combination`: every non-empty subset of the edits that apply, so the search sees them as one variant.
These are hypotheses for the exact judge, never equivalence claims."""
import itertools
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('weight_scope_unwrap', 'spill_slot_copy_collapse', 'init_sink_into_guard', 'weight_combination')
LIMIT = 15
CONSTANT = r'(?:NULL|0|\(\(void\s*\*\)\s*0\)|0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*'


def _wrappers(clean, start, end):
    """(do_start, open_brace, close_brace_end, while_end) of each `do { } while (0);` in the body."""
    found = []
    for hit in re.finditer(r'\bdo\s*\{', clean[start:end]):
        opening = start+hit.end()-1
        stop = close(clean, opening, '{', '}')
        tail = re.match(r'\s*while\s*\(\s*0\s*\)\s*;', clean[stop:end]) if stop else None
        if tail:
            found.append((start+hit.start(), opening, stop, stop+tail.end()))
    return found


def _self_contained(clean, inner, whole):
    inner_text = clean[inner[1]+1:inner[2]-1]
    labels = set(re.findall(rf'(?:^|[;{{}}])\s*({IDENT})\s*:(?!:)', inner_text))-{'default'}
    labels = {l for l in labels if l != 'case'}
    gotos = set(re.findall(rf'\bgoto\s+({IDENT})\s*;', inner_text))
    outside = clean[whole[0]:inner[0]]+clean[inner[3]:whole[1]]
    outside_gotos = set(re.findall(rf'\bgoto\s+({IDENT})\s*;', outside))
    outside_labels = set(re.findall(rf'(?:^|[;{{}}])\s*({IDENT})\s*:(?!:)', outside))
    if gotos-labels or labels & outside_gotos or gotos & outside_labels:
        return False
    if re.search(r'\b(?:break|continue)\b', inner_text):
        return False
    return not re.search(r'(?:^|[;{}])\s*(?:s32|u32|u16|s16|u8|s8|f32|f64|int|char|short|void)\s*\*?\s*\w+\s*;', inner_text)


def _unwrap_edit(wrapper):
    do_start, opening, stop, tail_end = wrapper
    return [(do_start, opening, ''), (stop, tail_end, '')]


def _scope_edits(part):
    """(function_wrapper_edits or None, inner_wrapper_edits) for the safe wrappers."""
    clean, start, end = part.clean, part.opening+1, part.end-1
    outer, inner = None, []
    for wrapper in _wrappers(clean, start, end):
        if not _self_contained(clean, wrapper, (start, end)):
            continue
        body = clean[wrapper[1]+1:wrapper[2]-1]
        if outer is None and clean[wrapper[3]:end].strip() in ('', '}'):
            outer = _unwrap_edit(wrapper)
        elif body.count(';') == 1 and not re.search(r'[{}:]', body):
            inner.append(_unwrap_edit(wrapper))
    return outer, [e for pair in inner for e in pair]


def _declared(part, name):
    return re.search(rf'(?:^|[;{{}}])\s*[A-Za-z_][\w \t\*]*[\s\*]{name}\s*;', part.clean[part.opening-0:part.end]) is not None or \
        re.search(rf'(?:^|[;{{}}\)])\s*[A-Za-z_][\w \t\*]*[\s\*]{name}\s*;', part.clean[:part.end]) is not None


def _collapse_edits(part, source):
    clean = part.clean
    out = []
    body_start = part.opening+1
    for copy in re.finditer(rf'(?<![\w.>])({IDENT})\s*=\s*({IDENT})\s*;', clean[body_start:part.end]):
        slot, temp = copy[1], copy[2]
        if slot == temp or not (_declared(part, slot) and _declared(part, temp)):
            continue
        absolute = body_start+copy.start()
        later = clean[body_start+copy.end():part.end]
        before = clean[body_start:absolute]
        sets = lambda text, n: len(re.findall(rf'(?<![\w.>]){n}\s*=(?!=)', text))
        if sets(clean[body_start:part.end], slot) != 1 or sets(clean[body_start:part.end], temp) != 1:
            continue
        if re.search(rf'\b{temp}\b', later) or len(re.findall(rf'\b{slot}\b', before)) > 1:
            continue
        # a stepped cursor (`slot += 0x10;`) inside a loop must start from `temp` again each time: renaming
        # would drop that reset, which is another program
        if any(re.search(rf'(?<![\w.>]){n}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)=)|(?:\+\+|--)\s*{n}\b', clean[body_start:part.end])
               for n in (slot, temp)):
            continue
        assign = re.search(rf'(?<![\w.>]){temp}\s*=(?!=)', before)
        if not assign:
            continue
        region = (body_start+assign.start(), absolute)
        edits = [(region[0]+m.start(), region[0]+m.end(), slot) for m in re.finditer(rf'\b{temp}\b', clean[region[0]:region[1]])]
        edits.append((absolute, body_start+copy.end(), ''))
        out.append(edits)
    return out


def _sink_edits(part):
    clean = part.clean
    out = []
    for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*=\s*({CONSTANT})\s*;(\s*)if\s*\(', clean[part.opening+1:part.end]):
        base = part.opening+1
        opening = base+hit.end()-1
        stop = close(clean, opening)
        brace = re.match(r'\s*\{', clean[stop:part.end]) if stop else None
        if not brace or re.search(rf'\b{hit[1]}\b', clean[opening:stop]):
            continue
        block = stop+brace.end()
        block_end = close(clean, block - 1, '{', '}')
        # the init must stay a program: the block may not assign it (m2c's `v = 1; if (!c) { v = 0; }` flag) and
        # nothing after the block may read it
        if block_end is None or re.search(rf'(?<![\w.>]){hit[1]}\s*=(?!=)', clean[block:block_end]) \
                or re.search(rf'\b{hit[1]}\b', clean[block_end:part.end]):
            continue
        statement = clean[base+hit.start():base+hit.start(3)]
        out.append([(base+hit.start(), base+hit.start(3)+len(hit[3]), ''), (block, block, '\n      '+statement)])
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    outer, inner = _scope_edits(part)
    groups = {}
    if outer:
        groups['U'] = outer
    if inner:
        groups['I'] = inner
    collapse = _collapse_edits(part, source)
    if collapse:
        groups['D'] = collapse[0]
    sink = _sink_edits(part)
    if sink:
        groups['S'] = sink[0]
    names = {'U': 'weight_scope_unwrap', 'I': 'weight_scope_unwrap', 'D': 'spill_slot_copy_collapse', 'S': 'init_sink_into_guard'}
    result = [(names[k], edit(source, v)) for k, v in groups.items()]
    # every guard's own init, and all of them: the first site alone was all a 1928-instruction collision sweep was
    # offered, where the third and fourth loops' counters were the ones that paid (8400 -> 8215)
    result += [('init_sink_into_guard', edit(source, site)) for site in sink[1:8]]
    if len(sink) > 1:
        result.append(('init_sink_into_guard', edit(source, [e for site in sink for e in site])))
    subsets = [c for n in range(len(groups), 1, -1) for c in itertools.combinations(sorted(groups), n)]
    for combo in subsets[:LIMIT]:
        result.append(('weight_combination', edit(source, [e for k in combo for e in groups[k]])))
    seen, out = set(), []
    for family, text in result:
        if text != source and text not in seen:
            seen.add(text)
            out.append((family, text))
    return out[:LIMIT + 12]
