"""A call m2c left an argument short, given the local that already holds the value the target passes.

m2c decides a callee's arguments from what it sees set up before the `jal`, and sometimes drops one the game passed:
an N64 function (KMC GCC 2.7.2) loaded a field into `$a0` (`lw $a0, 0xC4($s0)`), tested it and called a one-argument
callee with it, and the draft read the field into `temp_a0`, tested it, and then called `f()` with `M2C_UNK f(void);`.
The value was loaded into a different register (10 points of register rows) because nothing passed it on. Passing the
local the function already computed, `f(temp_a0)`, with the prototype given the parameter, was exact (10 -> 0).

`target_call_arity` adds a missing argument only when the target sets it to a constant or a global; this family is
the same step for a value the function computes. For each callee whose calls the C makes as often as the target
(paired in order), a call the target sets up with more argument registers than the C passes gets the missing ones
from the locals (or parameters) that carry evidence, one child per candidate:
- when the target's last write to the register before the call is a load (`lw $a0, 0xC4($s0)`), a variable whose last
  assignment before the call reads the same offset (`temp_a0 = M2C_FIELD(arg0, s32 *, 0xC4)`), so a variable
  written again between that load and the call is never offered;
- otherwise (a copy or a computation into the register), a variable m2c named after that register (`temp_a0`,
  `var_a1`), assigned before the call.
A variable already passed to the call is not offered again, and it must be declared in a scope that holds the call. A
missing slot the target sets to a constant or a global gets that value (all of them constants: `target_call_arity`).

The callee's declaration in the source changes with the call: its parameters are the callee's own matched definition's
types when the caller supplies it (`callees`: the matched C of the function's callees; a definition with another
number of parameters means no child), else the declaration's parameters plus the passed variables' types; `(void)`
counts as none, and an unprototyped `()` stays as it is. A varargs callee, a callee the header declares with another
number of parameters, or a call the C makes a different number of times than the target gives no child. MIPS only:
the evidence is the target's argument registers. The judge decides each child."""
import re

from . import target_call_arity_repairs as arity
from .csource import _blank
from .integer_repair_support import IDENT, edit, split_args, view
from .pattern_repairs import close

FAMILY = 'missing_call_argument_local'
FAMILIES = (FAMILY,)

LIMIT = 4  # children per call
ARGREG = arity.ARGREG
LOAD = re.compile(r'\$(?P<reg>\w+)\s*,\s*(?P<offset>-?(?:0x[0-9A-Fa-f]+|\d+))?\(\$\w+\)$')
LOADS = ('lw', 'lh', 'lhu', 'lb', 'lbu', 'lwu', 'ld')
QUALIFIER = r'(?:(?:const|volatile|unsigned|signed|struct|union|enum)\s+)'
DECLARATION = re.compile(rf'(?P<type>{QUALIFIER}*{IDENT}(?:\s+|\s*(?:\*\s*)+))(?P<name>{IDENT})\s*(?=[;=])')
NOT_TYPES = {'return', 'goto', 'case', 'else', 'do', 'sizeof', 'typedef', 'extern', 'static'}


def setups(asm):
    """[(callee, {register: (op, operands)})]: for each `jal` in order, the last instruction that wrote each argument
    register since the previous call, the delay slot included (the same pairing as target_call_arity.calls)."""
    found, written, pending = [], {}, None
    for op, args in arity._instructions(asm):
        dest = re.match(r'\$(\w+)', args)
        writes = dest and dest[1] in ARGREG and not op.startswith(('s', 'b', 'j'))
        if pending is not None:
            if writes:
                written[dest[1]] = (op, args)
            found.append((pending, written))
            pending, written = None, {}
            continue
        if op == 'jal':
            pending = args.split('+')[0].strip()
            continue
        if writes:
            written[dest[1]] = (op, args)
    return found


def _offset(setup):
    """The offset a load into the register reads at, or None when the last write is not a load."""
    if not setup or setup[0] not in LOADS:
        return None
    load = LOAD.match(setup[1])
    return int(load['offset'] or '0', 0) if load else None


def _python_blocks(clean, opening, end):
    """Every `{...}` in the function, the body included: [(open, close)]."""
    out, stack = [], []
    for pos in range(opening, end):
        if clean[pos] == '{':
            stack.append(pos)
        elif clean[pos] == '}' and stack:
            out.append((stack.pop(), pos))
    return out


_blocks = _python_blocks
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _blocks(clean, opening, end):
        found = _scan.block_pairs(clean, opening, end)
        return _python_blocks(clean, opening, end) if found is NotImplemented else found


def _variables(part, signature):
    """{name: (type, declared at, scope (open, close))} of the parameters and the plain declarations in the body."""
    found = {}
    whole = (part.opening, part.end - 1)
    for param in signature:
        hit = re.fullmatch(rf'\s*(?P<type>{QUALIFIER}*{IDENT}(?:\s+|\s*(?:\*\s*)+))(?P<name>{IDENT})\s*', param)
        if hit and hit['type'].split()[0] not in NOT_TYPES:
            found[hit['name']] = (' '.join(hit['type'].split()), part.opening, whole)
    blocks = _blocks(part.clean, part.opening, part.end)
    for hit in DECLARATION.finditer(part.clean, part.opening + 1, part.end - 1):
        prefix = part.clean[part.opening:hit.start()].rstrip()
        kind = hit['type'].split()[0]
        if prefix[-1:] not in ';{}' or kind in NOT_TYPES or hit['type'].strip() in NOT_TYPES:
            continue
        scope = min((b for b in blocks if b[0] < hit.start() < b[1]), key=lambda b: b[1] - b[0], default=whole)
        if hit['name'] in found:
            found[hit['name']] = None  # shadowed or declared twice: leave it to a reader that knows scopes
            continue
        found[hit['name']] = (' '.join(hit['type'].split()), hit.start(), scope)
    return {k: v for k, v in found.items() if v}


def _last_assignment(clean, name, start, at):
    """The expression of `name`'s last write between `start` and `at` when that write is a plain assignment, else ''
    (no write, or an update such as `+=` or `++` after it: not the plain value any more)."""
    n = re.escape(name)
    events = []
    for hit in re.finditer(rf'(?<![\w.>]){n}\s*=(?!=)', clean[start:at]):
        stop = clean.find(';', start + hit.end())
        if 0 <= stop < at:
            events.append((hit.start(), clean[start + hit.end():stop]))
    for hit in re.finditer(rf'(?<![\w.>]){n}\s*(?:[-+*/%&|^]|<<|>>)=|(?:\+\+|--)\s*{n}\b|(?<![\w.>]){n}\s*(?:\+\+|--)',
                           clean[start:at]):
        events.append((hit.start(), ''))
    return max(events)[1] if events else ''


def _reads_offset(expression, offset):
    text = expression.replace(' ', '')
    spellings = {f'0x{offset:X}', f'0x{offset:x}', str(offset)}
    if any(re.search(rf',{re.escape(s)}\)', text) or re.search(rf'\+{re.escape(s)}\)', text) for s in spellings):
        return True
    return offset == 0 and bool(re.search(r',0\)|^\*\(', text)) or bool(
        re.search(rf'(?:->|\.)unk_?{offset:X}\b', expression, re.I))


def _candidates(part, variables, args, at, slot, setup):
    """The variables that may carry argument `slot` at the call starting at `at`, best evidence first."""
    passed = {a.strip() for a in args}
    offset = _offset(setup)
    register = ARGREG[slot]
    ranked = []
    for name, (kind, declared, scope) in variables.items():
        if name in passed or not scope[0] <= at <= scope[1] or '[' in kind:
            continue
        is_param = declared == part.opening
        last = _last_assignment(part.clean, name, max(declared, part.opening), at)
        if offset is not None:
            if last and _reads_offset(last, offset):
                ranked.append((0, name))
        elif re.search(rf'_{register}$', name) and (last or is_param):
            ranked.append((1, name))
    return [name for _, name in sorted(ranked)]


def _params(text):
    text = text.strip()
    if not text or text == 'void':
        return []
    return [text[a:b].strip() for a, b in split_args(text)]


def _type_only(param):
    hit = re.fullmatch(rf'(?P<type>.*?[\s*])(?P<name>{IDENT})', param.strip())
    if hit and hit['name'] not in ('int', 'char', 'short', 'long', 'float', 'double', 'void', 'signed', 'unsigned') \
            and not re.fullmatch(r'[su](?:8|16|32|64)|f32|f64', hit['name']):
        return ' '.join(hit['type'].split())
    return ' '.join(param.split())


def _definition(callees, callee):
    """The parameter list of the callee's matched definition in `callees`, or None."""
    clean = _blank(callees or '')
    hits = list(re.finditer(rf'(?<![\w.>]){re.escape(callee)}\s*\(([^(){{}};]*)\)\s*{{', clean))
    return _params(hits[0][1]) if len(hits) == 1 else None


def _declared_count(header, callee):
    """The parameter counts the header declares `callee` with (an unprototyped `()` is left out)."""
    counts = set()
    for hit in re.finditer(rf'(?m)^[^\n;{{}}#]*\b{re.escape(callee)}\s*\(([^()]*)\)\s*;', _blank(header or '')):
        if '...' in hit[1]:
            counts.add(-1)
        elif hit[1].strip():
            counts.add(len(_params(hit[1])))
    return counts


def variants(source, name, asm, header='', callees=''):
    part = view(source, name)
    if not part or not asm:
        return []
    signature = re.search(rf'\b{re.escape(name)}\s*\(([^()]*)\)\s*$', part.clean[:part.opening].rstrip())
    variables = _variables(part, _params(signature[1]) if signature else [])
    jals = setups(asm)
    targets = {}
    for callee, regs in jals:
        targets.setdefault(callee, []).append(regs)
    result = []
    for callee, wanted in targets.items():
        if callee == name:
            continue
        sites = [(start, stop) for start, stop in _calls(part, callee)]
        if len(sites) != len(wanted):
            continue
        declaration = re.search(rf'(?m)^[^\n;{{}}#]*\b{re.escape(callee)}\s*\(([^()]*)\)\s*;',
                                part.clean[:part.opening])
        if declaration and '...' in declaration[1]:
            continue
        declared = _params(declaration[1]) if declaration and declaration[1].strip() else None
        matched = _definition(callees, callee)
        for (start, stop), regs in zip(sites, wanted):
            inner = part.clean[start:stop]
            args = [inner[a:b] for a, b in split_args(inner)] if inner.strip() else []
            count = max((ARGREG.index(r) + 1 for r in regs), default=0)
            if not len(args) < count <= 4:
                continue
            missing = range(len(args), count)
            values = {reg: arity._constant(*setup) for reg, setup in regs.items()}
            if all(values.get(ARGREG[k]) is not None for k in missing):
                continue  # all constants or globals: target_call_arity's step
            if matched is not None and len(matched) != count:
                continue  # the callee's own matched definition takes another number of arguments
            header_counts = _declared_count(header, callee)
            if header_counts and header_counts != {count}:
                continue
            if declared is not None and len(declared) > count:
                continue
            # (a slot the target sets to a constant or a global gets that, as target_call_arity would)
            choices = [[arity._number(values[ARGREG[k]])] if values.get(ARGREG[k]) is not None
                       else _candidates(part, variables, args, start, k, regs.get(ARGREG[k])) for k in missing]
            if not all(choices):
                continue
            for picks in _combinations(choices):
                added = ''.join((', ' if (args or i) else '') + pick for i, pick in enumerate(picks))
                edits = [(stop, stop, added)]
                if declaration and (declared is not None or declaration[1].strip() == 'void'):
                    if matched is not None:
                        params = [_type_only(p) for p in matched]
                    else:
                        params = [_type_only(p) for p in (declared or [])]
                        params += [variables[pick][0] if pick in variables else 's32' for pick in picks]
                    if len(params) != count:
                        continue
                    edits.append((declaration.start(1), declaration.end(1), ', '.join(params)))
                text = edit(source, edits)
                if text != source and text not in [t for _, t in result]:
                    result.append((FAMILY, text))
    return result


def _calls(part, callee):
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(callee)}\s*\(', part.clean[part.opening + 1:part.end - 1]):
        start = part.opening + 1 + hit.end()
        end = close(part.clean, start - 1)
        if end:
            yield start, end - 1


def _combinations(choices):
    """One pick per missing slot: each slot's candidates in turn with the others' best, at most LIMIT."""
    out = [tuple(c[0] for c in choices)]
    for k, options in enumerate(choices):
        for option in options[1:]:
            pick = tuple(option if i == k else c[0] for i, c in enumerate(choices))
            if len(set(pick)) == len(pick) and pick not in out:
                out.append(pick)
    return [p for p in out if len(set(p)) == len(p)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header', 'callees'),
          'order': 60, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py); `callees` from the caller
