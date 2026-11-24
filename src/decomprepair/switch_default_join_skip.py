"""A command loop's `default:` moved last and made to skip the result copy, with the out-of-line tail put in an arm.

The shape is an interpreter loop that runs one command per iteration and stops when the command says so:

    do {
        ...fetch...
        switch (op) {
            case 1: if (c) { ... } else { case 0: block_40: goto release; } break;
            case 2: work(); default: result = 0; break;
            case 6: if (e) { ... } else { goto block_40; } break;
            ...
        }
        goto complete;
        release: stop(); result = 1;
        complete:
        if (result & 0xFF) break;
    } while (++n < N);

KMC GCC 2.7.2 (jump.c) cross-jumps an unconditional jump first against the insns before its own label and only then
against the other jumps to that label; a label older than the pass is compared again in the next sweep, a label the
pass made is not. With `default: result = 0;` as the last arm, every `result = 0; break;` arm's `move $a0, $zero`
matches the default's and is redirected to the old default label, and the next sweep merges the arms wholesale. In
the target the default's `move $a0, $zero` sits last, falls into the test, and the arms still jump to a new label in
another arm's tail: at jump2 the default jumped to a label of its own, past an insn between the two labels that was
gone by then. That is a copy of the result into the tested variable (`done = result;`) that reload turned into a
no-op (both in `$a0`) and jump2 deleted before its main loop; the default's jump, then a jump to the next insn, is
deleted only when the sweep reaches it, after the arms. Written that way the default must not set `result`, so it
sets `done` and goes to the test (`default: done = 0; goto test;`), and `result`, read only through the copy, is a
byte (`u8`). The release code the arms `goto` is the arm the target has it in: the last `else { goto L; }`.

Children: the default's skip alone, with the result narrowed, the tail moved into its arm, and all three (in a
1315-instruction sound-sequence interpreter only all three together paid: 1770 -> 1400; the skip alone 1830).
Hypothesis for the no-op copy's deletion order; the cross-jump rules are read from jump.c. Proposals only; the
compiler and the byte judge decide."""
import re

from .csource import find

FAMILIES = ('switch_default_join_skip', 'switch_default_join_skip_narrow', 'switch_tail_into_arm',
            'switch_tail_into_arm_join_skip')

_TEST = re.compile(r'(\n[ \t]*)if \((?:\((\w+)\)|(\w+)) & 0xFF\)|(\n[ \t]*)if \((\w+)\)')


def _close(text, at):
    """Index of the brace closing the one at `at`."""
    depth = 0
    for i in range(at, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    return -1


def _fresh(text, base):
    name = base
    k = 2
    while re.search(r'\b%s\b' % name, text):
        name = '%s_%d' % (base, k)
        k += 1
    return name


def _switch(body):
    """(start of `switch`, its `{`, its `}`) for the first switch whose end is followed by a result test."""
    for m in re.finditer(r'\bswitch \(', body):
        brace = body.find('{', m.end())
        end = _close(body, brace)
        if end > 0:
            yield m.start(), brace, end


def _join_skip(body, brace, end, result, test_at, test_end, cond_var_span, narrow):
    inner = body[brace:end]
    d = re.search(r'\n[ \t]*default:[ \t]*\n(\s*)%s = (\w+);\s*\n\s*break;' % re.escape(result), inner)
    if not d:
        return None
    value = d.group(2)
    if not re.fullmatch(r'0x[0-9A-Fa-f]+|\d+', value):
        return None
    before = inner[:d.start()].rstrip()
    shared = not (before.endswith('break;') or before.endswith('{') or before.endswith('}'))
    done = _fresh(body, 'done')
    test_label = _fresh(body, 'command_test')
    if shared:
        new_inner = inner[:d.start()] + inner[d.start():].replace('default:', '', 1)
        new_inner = re.sub(r'\n[ \t]*\n(\s*%s = )' % re.escape(result), r'\n\1', new_inner, count=1)
    else:
        new_inner = inner[:d.start()] + inner[d.end():]
    indent = re.search(r'\n([ \t]*)case ', inner)
    pad = indent.group(1) if indent else '    '
    new_inner = new_inner.rstrip() + '\n\n%sdefault:\n%s  %s = %s;\n%s  goto %s;\n' % (
        pad, pad, done, value, pad, test_label)
    tail = body[end:test_at]
    lead = re.match(r'\n[ \t]*', body[test_at:]).group(0)
    a, b = cond_var_span
    cond = body[test_at:a] + done + body[b:test_end]
    out = body[:brace] + new_inner + tail + '%s%s = %s;%s%s:%s' % (lead, done, result, lead, test_label,
                                                                    cond) + body[test_end:]
    decl = re.search(r'\n([ \t]*)((?:unsigned |signed )?\w+) %s;' % re.escape(result), out)
    if not decl:
        return None
    kind = 'u8' if narrow else decl.group(2)
    out = out[:decl.start()] + '\n%s%s %s;\n%ss32 %s;' % (decl.group(1), kind, result, decl.group(1), done) + \
        out[decl.end():]
    return out


def _tail_into_arm(body, brace, end, test_at):
    """Move `goto C; L: S C:` after the switch into the last `{ goto X; }` arm that reaches L."""
    after = body[end + 1:test_at]
    m = re.match(r'(\s*)goto (\w+);\s*\n\s*(\w+):\s*\n(.*?)\n(\s*)%s:\s*' % r'(\w+)', after, re.S)
    if not m or m.group(2) != m.group(6):
        return None
    label, stmts = m.group(3), m.group(4)
    if re.search(r'\bgoto\b|\bbreak\b|\bcase\b|\{', stmts):
        return None
    inner = body[brace:end]
    tramp = re.search(r'\{(\s*)((?:(?:case [^:]+|\w+):\s*)+)goto %s;\s*\}' % re.escape(label), inner)
    names = {label}
    cases = []
    if tramp:
        labels = re.findall(r'(case [^:]+|\w+):', tramp.group(2))
        cases = [x + ':' for x in labels if x.startswith('case ')]
        names |= {x for x in labels if not x.startswith('case ')}
    hosts = [h for h in re.finditer(r'\{\s*goto (\w+);\s*\}', inner) if h.group(1) in names]
    hosts = [h for h in hosts if not (tramp and tramp.start() <= h.start() < tramp.end())]
    if not hosts:
        return None
    host = hosts[-1]
    pad = re.search(r'\n([ \t]*)[^\s]', inner[host.end():]) or re.search(r'\n([ \t]*)', inner)
    pad = pad.group(1) + '  '
    lines = [x.strip() for x in stmts.split('\n') if x.strip()]
    block = '{\n' + ''.join('%s%s\n' % (pad, c) for c in cases) + '%s%s:\n' % (pad, label) + \
        ''.join('%s%s\n' % (pad, x) for x in lines) + pad[:-2] + '}'
    edits = [(host.start(), host.end(), block)]
    if tramp:
        edits.append((tramp.start(), tramp.end(), '{\n%sgoto %s;\n%s}' % (pad, label, pad[:-2])))
    edits.sort(reverse=True)
    for a, b, t in edits:
        inner = inner[:a] + t + inner[b:]
    for n in names - {label}:
        inner = re.sub(r'\bgoto %s;' % re.escape(n), 'goto %s;' % label, inner)
    rest = body[end:end + 1] + m.group(1).rstrip(' \t') + body[end + 1 + m.end():]
    return body[:brace] + inner + rest


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    s, e = span
    body = source[s:e]
    out = []
    for start, brace, end in _switch(body):
        t = _TEST.search(body, end)
        if not t or t.start() - end > 1200:
            continue
        if t.group(1) is not None:
            result = t.group(2) or t.group(3)
            vs = t.start(2) if t.group(2) else t.start(3)
        else:
            result = t.group(5)
            vs = t.start(5)
        cond_span = (vs, vs + len(result))
        test_at = t.start()
        close = body.find(')', vs + len(result))
        test_end = close + 1
        if t.group(1) is not None:
            test_end = body.find('0xFF)', vs) + len('0xFF)')
        for fam, narrow in ((FAMILIES[0], False), (FAMILIES[1], True)):
            r = _join_skip(body, brace, end, result, test_at, test_end, cond_span, narrow)
            if r:
                out.append((fam, source[:s] + r + source[e:]))
        moved = _tail_into_arm(body, brace, end, test_at)
        if moved:
            out.append((FAMILIES[2], source[:s] + moved + source[e:]))
            for st, br, en in _switch(moved):
                t2 = _TEST.search(moved, en)
                if not t2:
                    continue
                g = 2 if t2.group(1) is not None and t2.group(2) else 3 if t2.group(1) is not None else 5
                vs2 = t2.start(g)
                te2 = (moved.find('0xFF)', vs2) + 5) if t2.group(1) is not None else moved.find(')', vs2) + 1
                r = _join_skip(moved, br, en, result, t2.start(), te2, (vs2, vs2 + len(result)), True)
                if r:
                    out.append((FAMILIES[3], source[:s] + r + source[e:]))
                break
        break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
