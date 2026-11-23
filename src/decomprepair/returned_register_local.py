"""The local the target returns, read off the register its epilogue copies into `$v0`.

A function that makes an object and sets it up returns the object: an N64 function (KMC GCC 2.7.2) kept the pointer it
got from an allocator in `$s0`, set fields through it, and ended with `move $v0, $s0` before restoring its saved
registers. Its saved best returned `temp_s1`, a field it had loaded (`lw $s1, 0xE0($s0)`) and passed to a callee, so
the compiler copied `$s1` into `$v0` and kept the last store going through `$s0`: two register rows, score 10. The only
edit was `return (s32) temp_s0;` (10 -> 0).

m2c names a local by the register it first lived in (`temp_s0`, `var_s2`), and a function's saved registers hold the
same value from where they are set to the end, so the register the epilogue copies into `$v0` names the local to
return. The family reads the target's last write to `$v0` before its `jr $ra`; when it is a copy from another register
(`move`, `addu`/`or` with `$zero`), the C's single `return X;` at the end of the function is offered, one child each:
- the local m2c named after that register (`temp_s0`, `var_s0`), assigned before the return;
- the parameter the prologue copied into that register (`move $s2, $a0`: `arg0`);
- the function's other pointer locals assigned before the return (an object pointer is the usual value).
A child keeps the function's declared return type, so its callers see the same type, and casts the local to it when its
declared type differs (`(s32) temp_s0`). Nothing is offered when the local already returned is the register's own, when
the function returns a narrow type (`s8`, `u16`, ...) or a float, when it has more than one `return`, when its last
write to `$v0` is a load, a constant or a call's result, or when the target's code has a branch or a call between that
copy and the return. MIPS only: the evidence is the target's epilogue. Each child is judged."""
import re

from . import mips_regions as flow
from .integer_repair_support import IDENT, edit, split_args, view

FAMILY = 'returned_register_local'
FAMILIES = (FAMILY,)

LIMIT = 4
NARROW = re.compile(r'\b(?:[su](?:8|16)|char|short|f32|f64|float|double|void)\b')
LINE = re.compile(r'^\s*(?:/\*.*?\*/)?\s*(?P<op>[a-z][\w.]*)\s*(?P<args>[^\n]*)$')
QUALIFIER = r'(?:(?:const|volatile|unsigned|signed|struct|union|enum)\s+)'
DECLARATION = re.compile(rf'(?P<type>{QUALIFIER}*{IDENT}(?:\s+|\s*(?:\*\s*)+))(?P<name>{IDENT})\s*(?=[;=])')
NOT_TYPES = {'return', 'goto', 'case', 'else', 'do', 'sizeof', 'typedef', 'extern', 'static'}


def _instructions(asm):
    out = []
    for line in (asm or '').splitlines():
        hit = LINE.match(line)
        if hit and not line.strip().startswith(('.', 'glabel', 'endlabel')) and not hit['op'].endswith(':'):
            out.append((hit['op'], hit['args'].strip()))
    return out


def returned_register(asm):
    """The register the target's epilogue copies into `$v0`, or None. Read backwards from the single `jr $ra`: the
    last write to `$v0` must be a plain register copy, with no call, branch or jump between it and the return."""
    rows = _instructions(asm)
    returns = [i for i, (op, args) in enumerate(rows) if op == 'jr' and args == '$ra']
    if len(returns) != 1:
        return None
    for op, args in reversed(rows[:returns[0] + 2]):
        if op == 'jr':
            continue
        if op in flow.CALLS | flow.CONDITIONAL | flow.JUMPS:
            return None
        if re.match(r'\$v0\b', args) and op not in flow.STORES:
            operands = re.findall(r'\$(\w+)', args)
            if op == 'move' and len(operands) == 2:
                source = operands[1]
            elif op in ('addu', 'or', 'daddu') and len(operands) == 3 and 'zero' in operands[1:]:
                source = operands[2] if operands[1] == 'zero' else operands[1]
            else:
                return None
            return None if source in ('zero', 'v0', 'sp', 'ra') else source
    return None


def _copied_parameter(asm, register):
    """The argument register the prologue copied into `register` before any call, or None."""
    for op, args in _instructions(asm):
        if op in flow.CALLS | flow.CONDITIONAL | flow.JUMPS:
            return None
        hit = re.fullmatch(rf'\${register}\s*,\s*\$(a[0-3])(?:\s*,\s*\$zero)?', args) if op in ('move', 'addu', 'or') \
            else None
        if hit:
            return int(hit[1][1])
        if re.match(rf'\${register}\b', args) and op not in flow.STORES:
            return None
    return None


def _variables(part, params):
    found = {}
    for index, param in enumerate(params):
        hit = re.fullmatch(rf'\s*(?P<type>{QUALIFIER}*{IDENT}(?:\s+|\s*(?:\*\s*)+))(?P<name>{IDENT})\s*', param)
        if hit:
            found[hit['name']] = (' '.join(hit['type'].split()), index)
    for hit in DECLARATION.finditer(part.clean, part.opening + 1, part.end - 1):
        prefix = part.clean[part.opening:hit.start()].rstrip()
        if prefix[-1:] not in ';{}' or hit['type'].split()[0] in NOT_TYPES or hit['type'].strip() in NOT_TYPES:
            continue
        found[hit['name']] = None if hit['name'] in found else (' '.join(hit['type'].split()), None)
    return {k: v for k, v in found.items() if v}


def _same(a, b):
    return ' '.join(a.replace('*', ' * ').split()) == ' '.join(b.replace('*', ' * ').split())


def variants(source, name, asm):
    part = view(source, name)
    if not part or not asm:
        return []
    register = returned_register(asm)
    if not register:
        return []
    head = re.search(rf'(?P<result>[^;{{}}]*?)\b{re.escape(name)}\s*\((?P<params>[^()]*)\)\s*$',
                     part.clean[:part.opening].rstrip())
    if not head:
        return []
    result_type = ' '.join(re.sub(r'\b(?:static|inline|extern)\b', ' ', head['result']).split())
    if not result_type or NARROW.search(result_type):
        return []
    returns = list(re.finditer(r'\breturn\b\s*(?P<value>[^;]*);', part.clean[part.opening:part.end]))
    if len(returns) != 1 or not returns[0]['value'].strip():
        return []
    ret = returns[0]
    value_at = part.opening + ret.start('value')
    value = ret['value'].strip()
    if not re.fullmatch(r'\s*}\s*', part.clean[part.opening + ret.end():part.end]):
        return []  # the return must end the function
    params_text = head['params'].strip()
    params = [] if params_text in ('', 'void') else [params_text[a:b] for a, b in split_args(params_text)]
    variables = _variables(part, params)
    returned = re.sub(r'^\(\s*[^()]*\)\s*', '', value).strip()  # a cast the draft already wrote
    if re.fullmatch(rf'\w+_{register}', returned):
        return []  # it already returns the register's own local
    body_before = part.clean[part.opening:value_at - len('return ')]

    def assigned(local):
        return variables[local][1] is not None or re.search(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)', body_before)

    ranked = []
    for local, (kind, index) in variables.items():
        if local == returned or '[' in kind or not assigned(local):
            continue
        if re.fullmatch(rf'\w+_{register}', local):
            ranked.append((0, local))
        elif index is not None and index == _copied_parameter(asm, register):
            ranked.append((1, local))
        elif '*' in kind and index is None:
            ranked.append((2, local))
    result = []
    for _, local in sorted(ranked)[:LIMIT]:
        kind = variables[local][0]
        written = local if _same(kind, result_type) else f'({result_type}) {local}'
        text = edit(source, [(value_at, value_at + len(ret['value'].rstrip()), written)])
        if text != source:
            result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'),
          'order': 60, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
