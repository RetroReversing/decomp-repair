"""The float literals stored after a call, kept in locals assigned right after the call.

m2c writes every float constant at its store: `p->f4 = 1.0f; ... p->f6C = 1.0f; p->f70 = 1.0f;`. After a call each
one is a constant the compiler loads next to its first store, and the first scheduler leaves the loads where the stores
are. The game kept the literals in locals (`one = 1.0f;` right after the call): the loads are then insns of their own
ahead of the stores, they land at the top of the block, and the call's result (`$f0`) is still live when they are
allocated, so they take `$f2`/`$f4` and the block's later temporaries take `$f0`. In a 392-instruction object
initialiser the block (call result stored, a zero read back, nineteen stores, three float literals) was one change
away from exact and all its rows matched with the literals in locals: 2597 -> 2177 with the locals assigned before the
call, 1747 -> 1612 with them after it.

`variants` offers, for the first call statement (`f(...)` or `x = f(...)`) that is followed within thirty statements by
at least three stores of float literals (`... = 1.0f;`) with a literal repeated or two literals, locals for the
distinct literals (`f32`, declared at the top of the function) assigned right after the call and used in the stores;
the same with the call's result stored through a temporary after the assignments (`t = f(..); lit = ..; x = t;`); and
the assignments before the call. At most 3."""
import re

from .csource import _blank, find

FAMILY = 'float_literal_locals'
FAMILIES = (FAMILY,)
LIMIT = 3
LITERAL = r'-?\d+\.\d*(?:[eE][-+]?\d+)?f'
STORE = re.compile(rf'(?m)^(?P<head>[ \t]*[^;\n{{}}]*?=\s*)(?P<value>{LITERAL});[ \t]*$')
CALL = re.compile(r'(?m)^(?P<indent>[ \t]*)(?:(?P<lhs>[^;\n{}]*?)\s=\s)?(?P<call>[A-Za-z_]\w*\s*\([^;\n]*\));[ \t]*$')


def _name(literal, taken):
    base = 'lit_' + re.sub(r'\W', '_', literal.rstrip('f').replace('.', 'p').replace('-', 'm'))
    name, k = base, 2
    while name in taken:
        name, k = f'{base}_{k}', k + 1
    taken.add(name)
    return name


def variants(source, name):
    """Proposals: the locals after the call (with the result stored last), after it, and before it."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    for call in CALL.finditer(clean, span[0], span[1]):
        if re.match(r'\s*(?:if|while|for|switch|return|else)\b', call['call']):
            continue
        run_start = call.end() + 1
        stores, scanned, at = [], 0, run_start
        while scanned < 30 and at < span[1]:
            end = clean.find('\n', at)
            end = span[1] if end < 0 else end
            line = clean[at:end]
            if re.search(r'[{}]|\b(?:if|while|for|do|switch|goto|return)\b', line):
                break
            hit = STORE.fullmatch(line)
            if hit:
                stores.append((at, end, hit))
            scanned += 1
            at = end + 1
        values = [hit['value'] for _, _, hit in stores]
        if len(stores) < 3 or (len(set(values)) == len(values) and len(values) < 2):
            continue
        taken = set(re.findall(r'[A-Za-z_]\w*', clean[span[0]:span[1]]))
        names = {value: _name(value, taken) for value in dict.fromkeys(values)}
        edited = []
        for start, end, hit in reversed(stores):
            edited.append((start, end, f"{hit['head']}{names[hit['value']]};"))
        text = source
        for start, end, new in edited:
            text = text[:start] + new + text[end:]
        indent = call['indent']
        assigns = ''.join(f'{indent}{n} = {value};\n' for value, n in names.items())
        call_start, call_end = call.start(), call.end() + 1
        # (offsets before the first edited store are unchanged: the call lies before the run)
        opening = clean.find('{', span[0])
        declaration_line = text.find('\n', opening) + 1
        declared = ''.join(f'  f32 {n};\n' for n in names.values())
        after = text[:call_end] + assigns + text[call_end:]
        before = text[:call_start] + assigns + text[call_start:]
        results = []
        if call['lhs']:
            temp = _name('r', taken)
            split = (text[:call_start] + f"{indent}{temp} = {call['call']};\n" + assigns
                     + f"{indent}{call['lhs']} = {temp};\n" + text[call_end:])
            results.append(split)
            declared_split = declared + f'  f32 {temp};\n'
        for variant in (after, before):
            results.append(variant)
        out = []
        for index, variant in enumerate(results):
            extra = declared_split if call['lhs'] and index == 0 else declared
            out.append(variant[:declaration_line] + extra + variant[declaration_line:])
        return [(FAMILY, t) for t in dict.fromkeys(out)][:LIMIT]
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}
