"""Stack slots an agent forced into m2c's frame struct with `volatile`, turned back into ordinary locals.

When a draft's frame is a few words short of the target's, the quick fix is a `volatile` member in m2c's `locals`
struct at the spill's offset: a call's result stored at `0xCC($sp)` and read at the end, a pointer kept at `0xD4` and
reloaded for each use, the address of another member kept at `0xDC`. It reproduces the offsets and the reloads, but a
member of that struct is a memory object the scheduler must keep in order, and its store is placed with the
instruction that makes it: where the target's `sw $v0, 0xCC($sp)` came after the loads and compares set up beside it,
the member's store sits right after the call. The target's were spills: pseudos the register allocator left without a
register, stored where the second scheduler puts a store (which it moves late) and reloaded for each use, `$t0` for
the address of a field. A plain local does the same, and the struct then ends where its real members do.

The variants rewrite the struct's tail: from the first `volatile` member (and the padding member before it, which
the spill slots' own 8-byte alignment makes again) to the end of the struct go, and
 - a volatile member assigned a call's result or any value becomes a plain local of its type, declared after the struct;
 - a volatile member assigned only `&locals.other` (the address of another member) is replaced by that expression
   at each read: the loop optimizer hoists it and the spill is the compiler's.
Offered all together, then with the members that are not addresses only. The frame is the judge's to compare;
a gap that is left is for `halfword_store_normalization` and `spill_normalization`.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'volatile_slot_demotion'
FAMILIES = (FAMILY,)
_STRUCT = re.compile(r'(?m)^(?P<indent>[ \t]*)struct[ \t]*\{[ \t]*\n(?P<body>(?:[^{}]*\n)*?)[ \t]*\}[ \t]*(?P<name>' + IDENT + r')[ \t]*;[ \t]*\n')
_MEMBER = re.compile(r'(?m)^[ \t]*(?P<text>[^;{}\n]+);[ \t]*\n')


def _members(body):
    return [(hit.start(), hit.end(), hit['text'].strip()) for hit in _MEMBER.finditer(body)]


def _name_and_type(text):
    plain = re.sub(r'\bvolatile\b', '', text)
    hit = re.search(r'(' + IDENT + r')\s*(\[[^\]]*\])?\s*$', plain)
    if not hit:
        return None, None
    kind = re.sub(r'\s*\*\s*', ' *', plain[:hit.start()].strip())
    return hit[1], ' '.join(kind.split())


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    structure = _STRUCT.search(clean, part.opening, part.end)
    if not structure:
        return []
    body = structure['body']
    members = _members(body)
    volatile = [i for i, (_, _, text) in enumerate(members) if re.search(r'\bvolatile\b', text) and '[' not in text]
    if not volatile or any(re.search(r'\bvolatile\b', text) and '[' in text for _, _, text in members):
        return []
    first = volatile[0]
    # the tail must be volatile scalars and padding arrays only
    for i in range(first, len(members)):
        text = members[i][2]
        if i not in volatile and not re.fullmatch(r'u8\s+\w+\[\d+\]', text):
            return []
    cut = first - 1 if first and re.fullmatch(r'u8\s+\w+\[\d+\]', members[first - 1][2]) else first
    holder = structure['name']
    scope = clean[structure.end():part.end]
    plans = []
    for i in volatile:
        member, kind = _name_and_type(members[i][2])
        uses = list(re.finditer(rf'(?<![\w.>]){holder}\.{member}\b', scope))
        if member is None or not uses:
            return []
        assigns = [u for u in uses if re.match(r'[ \t]*=(?!=)', scope[u.end():])]
        if len(assigns) != 1:
            return []
        rest = re.match(r'[ \t]*=[ \t]*([^;]*);', scope[assigns[0].end():])
        value = rest[1].strip() if rest else None
        address = re.fullmatch(rf'&\s*{holder}\.{IDENT}', value or '')
        plans.append(dict(member=member, kind=kind, uses=uses, assign=assigns[0], value=value, address=bool(address)))
    result = []
    for subset in ([plans], [[p for p in plans if not p['address']]] if any(p['address'] for p in plans) and any(not p['address'] for p in plans) else []):
        chosen = subset[0]
        if not chosen:
            continue
        edits = [(structure.start('body') + members[cut][0], structure.end('body'), '')]
        locals_ = []
        base = structure.end()
        for plan in plans:
            if plan not in chosen:
                continue
            local = f'__repair_slot_{plan["member"]}'
            if plan['address']:
                for use in plan['uses']:
                    if use is plan['assign']:
                        stop = scope.index(';', use.end()) + 1
                        line_start = scope.rfind('\n', 0, use.start()) + 1
                        line_end = scope.index('\n', stop) + 1
                        edits.append((base + line_start, base + line_end, ''))
                    else:
                        edits.append((base + use.start(), base + use.end(), plan['value']))
            else:
                locals_.append(f'    {plan["kind"]}{"" if plan["kind"].endswith("*") else " "}{local};\n')
                for use in plan['uses']:
                    edits.append((base + use.start(), base + use.end(), local))
        if len(chosen) != len(plans):
            # members left volatile stay in the struct: put the tail back for them
            keep_text = ''.join(f'{" " * 8}{members[i][2]};\n' for i in range(cut, len(members)) if any(p['member'] == _name_and_type(members[i][2])[0] for p in plans if p not in chosen) or (i not in volatile and False))
            edits[0] = (edits[0][0], edits[0][1], keep_text)
        edits.append((structure.end(), structure.end(), ''.join(locals_)))
        text = edit(source, edits)
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILY, text))
    return result
