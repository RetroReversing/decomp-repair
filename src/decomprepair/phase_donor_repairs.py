"""A later phase's scratch values written through the dead locals of an earlier phase, as one child.

m2c gives every value it recovers a name of its own, and the repair that splits a shared scratch variable into a
union (`phase_union_repairs`) adds one more. GCC 2.7.2 hands out registers per source variable by
`floor_log2(refs) * refs / live_length` (global.c), so a second phase whose clamp variable, address and product
are fresh pseudos is ranked, and numbered, differently from the game's, where the second phase reused the first
phase's variables. Found on a 181-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) whose
two halves each clamp a scaled difference and add it to a halfword of a record: only eight register rows stood
between the saved best (40) and the match, in the second half, and three edits made them go, none of which a
one-step search could see:

* `scalar_member_local`: the second clamp variable was the `.value` member of the register union a phase repair
  had added; as a plain local of its own it is an ordinary pseudo (40 -> 60 alone, the union's pseudo had
  ranked itself past the pointer's);
* `address_donor`: the second half's record pointer (`T = (void *) (E);`, a pointer local) is the first half's
  address variable again (`D = (s32) (E);`, `D` read through `(char *) D` there), so the one long pseudo of the
  first half outranks the second clamp variable and takes the register the target has (60 -> 10);
* `product_donor`: the second clamp is `V = ((s32) (a * b)) >> 7;`, written `D = a * b; V = D >> 7;` through the
  first clamp's variable `D` (dead there; it held `D = x * b; D >>= 7;`), so `mflo` and `sra` share its register
  where a product temporary of its own took `$v0` (10 -> 0).

The first two lower the score only together with the third's neighbour (each alone: 60, then 15 -> 10 -> 0), so
`variants` offers the whole combination first, then each subset. The reading of the allocator (priorities and
`regs_someone_prefers`) is from global.c; which donor the game used is a guess that the exact judge decides.
Only straight-line-or-branching code is rewritten: a function with a loop or a `goto` is left alone, because a
donor read after the loop's back edge is not dead. A candidate rewrite; the compiler/link judge decides.
"""
import itertools
import re

from .integer_repair_support import IDENT, edit, view
from .line_scan import with_local

FAMILY = 'phase_donor'
SCALAR = 'scalar_member_local'
ADDRESS = 'address_donor'
PRODUCT = 'product_donor'
FAMILIES = (FAMILY, SCALAR, ADDRESS, PRODUCT)
LIMIT = 24
WORD = r'(?:s32|u32|int|unsigned(?:\s+int)?|signed(?:\s+int)?|long)'
_LOOPS = re.compile(r'\b(?:for|while|do|goto)\b|^\s*\w+\s*:(?!:)', re.M)
_UNION = re.compile(rf'(?:register\s+)?union\s*(?:{IDENT}\s*)?{{(?P<members>[^{{}}]*)}}\s*(?P<name>{IDENT})\s*;')
_PRODUCT = re.compile(
    rf'(?<![\w.>])(?P<lhs>{IDENT}(?:\.{IDENT})?)\s*=\s*\(\s*(?:\((?:s32|int)\)\s*)?\((?P<p>[^;{{}}()]*\*[^;{{}}()]*)\)\s*\)'
    rf'\s*>>\s*(?P<k>\d{{1,2}})\s*;')
_ADDRESS = re.compile(rf'(?<![\w.>])(?P<t>{IDENT})\s*=\s*\(void\s*\*\)\s*(?P<e>\([^;{{}}]*\))\s*;')


def _mentions(clean, name, start, end):
    return [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[start:end])]


def _words(part):
    """Plain 32-bit integer locals: name -> (start, end) of the declaration statement; escaped ones are left out."""
    found = {}
    for m in re.finditer(rf'(?m)^[ \t]*(?:register\s+)?{WORD}\s+(?P<name>{IDENT})\s*;', part.clean[part.opening + 1:part.end]):
        name = m['name']
        if re.search(rf'&\s*{re.escape(name)}\b', part.body) or len(re.findall(rf'\b{re.escape(name)}\s*[;=,]', part.body)) < 1:
            continue
        found[name] = (part.opening + 1 + m.start(), part.opening + 1 + m.end())
    return found


def _dead_before(part, name, decl_end, at):
    """The local is assigned and used before `at` and mentioned nowhere from `at` on (no loops: see `variants`)."""
    hits = _mentions(part.clean, name, decl_end, part.end)
    before = [m for m in hits if decl_end + m.start() < at]
    after = [m for m in hits if decl_end + m.start() >= at]
    if after or len(before) < 2:
        return None
    assigned = any(re.match(rf'{re.escape(name)}\s*(?:[-+*&|^]|<<|>>)?=(?!=)', part.clean[decl_end + m.start():]) for m in before)
    return decl_end + before[-1].start() if assigned else None


def _scalar_member_local(source, name):
    """`U.value` of a register union (a phase repair's scratch storage) as a plain local of the member's type."""
    part = view(source, name)
    if not part:
        return []
    out = []
    for union in _UNION.finditer(part.clean[part.opening + 1:part.end]):
        members = dict((n, t.strip()) for t, n in re.findall(rf'([\w\s]+?)\s+\*?\s*({IDENT})\s*;', union['members'].replace('*', ' ')))
        if 'value' not in members or 'pointer' not in members:
            continue
        u = union['name']
        uses = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(u)}\.value\b', part.clean[part.opening + 1:part.end])]
        if not uses or not re.search(rf'(?<![\w.>]){re.escape(u)}\.pointer\b', part.body):
            continue
        local = f'{u}_value'
        if re.search(rf'\b{re.escape(local)}\b', part.clean):
            continue
        declaration = with_local(source, part, f'{members["value"]} {local};')
        if not declaration:
            continue
        edits = [declaration] + [(part.opening + 1 + m.start(), part.opening + 1 + m.end(), local) for m in uses]
        out.append(edit(source, edits))
    return out


def _address_donor(source, name):
    """One source per pointer local assigned once from `(void *) (E)`: that address kept in a dead integer local."""
    part = view(source, name)
    if not part or _LOOPS.search(part.body):
        return []
    words = _words(part)
    out = []
    for assignment in _ADDRESS.finditer(part.clean[part.opening + 1:part.end]):
        t = assignment['t']
        at = part.opening + 1 + assignment.start()
        declaration = re.search(rf'(?m)^[ \t]*(?:register\s+)?void\s*\*\s*{re.escape(t)}\s*;[ \t]*\n?', part.clean[part.opening + 1:part.end])
        if not declaration or len(re.findall(rf'(?<![\w.>]){re.escape(t)}\s*=(?!=)', part.body)) != 1:
            continue
        if re.search(rf'&\s*{re.escape(t)}\b', part.body):
            continue
        after = part.opening + 1 + assignment.end()
        uses = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(t)}\b', part.clean[after:part.end])]
        if not uses:
            continue
        for donor, (_, decl_end) in words.items():
            last = _dead_before(part, donor, decl_end, at)
            # The donor must be read as an address somewhere (`(char *) D`): the game used it as one.
            if last is None or not re.search(rf'\(\s*(?:const\s+)?[\w\s]+\*\s*\)\s*\(?\s*{re.escape(donor)}\b', part.body):
                continue
            pointer = f'((void *) {donor})'
            edits = [(at, part.opening + 1 + assignment.end(), f'{donor} = (s32) {assignment["e"]};'),
                     (part.opening + 1 + declaration.start(), part.opening + 1 + declaration.end(), '')]
            edits += [(after + m.start(), after + m.end(), pointer) for m in uses]
            out.append(edit(source, edits))
            break
    return out


def _product_donor(source, name):
    """`V = ((s32) (a * b)) >> k;` as `D = a * b; V = D >> k;` through each dead local that held such a product."""
    part = view(source, name)
    if not part or _LOOPS.search(part.body):
        return []
    words = _words(part)
    out = []
    for stage in _PRODUCT.finditer(part.clean[part.opening + 1:part.end]):
        at = part.opening + 1 + stage.start()
        ranked = []
        for donor, (_, decl_end) in words.items():
            if donor == stage['lhs'] or re.search(rf'(?<![\w.>]){re.escape(donor)}\b', stage['p'] + stage['lhs']):
                continue
            last = _dead_before(part, donor, decl_end, at)
            if last is None:
                continue
            # Ones that held a shifted product first (`D = x * b; D >>= k;`), then the nearest last mention.
            held = bool(re.search(rf'(?<![\w.>]){re.escape(donor)}\s*>>=', part.body[:at - part.opening - 1]))
            ranked.append((not held, -last, donor))
        for _, _, donor in sorted(ranked)[:2]:
            statement = f'{donor} = {stage["p"].strip()}; {stage["lhs"]} = {donor} >> {stage["k"]};'
            out.append(edit(source, [(at, part.opening + 1 + stage.end(), statement)]))
    return out


def variants(source, name):
    if not view(source, name):
        return []
    pools = ((SCALAR, _scalar_member_local), (ADDRESS, _address_donor), (PRODUCT, _product_donor))
    results = []
    seen = {source}
    # Every subset of the three steps, the whole combination first: each step's alternatives are tried in turn.
    for size in (3, 2, 1):
        for chosen in itertools.combinations(pools, size):
            partial = [(source, ())]
            for family, step in chosen:
                partial = [(rewritten, labels + (family,)) for text, labels in partial for rewritten in step(text, name)
                           if rewritten != text]
            for text, labels in partial:
                if text in seen:
                    continue
                seen.add(text)
                results.append((FAMILY if len(labels) > 1 else labels[0], text))
    return results[:LIMIT]
