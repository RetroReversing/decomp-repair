"""A counter stepped before the call that reads it, where the target passes the value it had before the step.

m2c can lose a copy made in front of a join. A loop that draws a column of rows keeps `y` beside its index; the target
copies it to the argument register (`addu $a2, $s1, $zero`, on each path to the join) and only then steps it
(`addiu $s1, $s1, 0xA`), but the draft writes

    y += 0xA;
    i += 1;
    draw(item, 0xA7, y);

which passes the value after the step. When the assembly shows that copy for the argument's own register ($a0..$a3),
the step's constant and the register stepped, and nothing writes either before the callee, the run of steps in front of
the call is written after it. The second child also writes the counter's companions off the counter
(`counter_companion`), which only fires once the steps are the loop body's last statements, and rejoins the draft's
`goto` arms (`m2c_goto_arm_chain`) when it has them: in an N64 function (SN GCC 2.8.1) neither of those two edits
improved on the other's absence (775), and together with this one they were exact.
"""
import re

from .counter_companion_repairs import variants as companions
from .integer_repair_support import IDENT, calls, edit, integer, split_args, view
from .m2c_join_ladder import CHAIN
from .m2c_join_ladder import variants as join_ladders

FAMILY = 'counter_step_after_reader'
COMBINED = 'counter_step_after_reader_companion'
FAMILIES = (FAMILY, COMBINED)

_NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)[uU]?'
_STEP = re.compile(rf'(?<![\w.>])(?:(?P<a>{IDENT})\s*\+=\s*(?P<k>{_NUM})|(?P<b>{IDENT})\s*=\s*(?P=b)\s*\+\s*'
                   rf'(?P<k2>{_NUM})|(?P<c>{IDENT})\s*\+\+)\s*;')
# one instruction of a listing, with or without its address comment
_INSN = re.compile(r'^\s*(?:/\*[^*\n]*\*/\s*)?(?P<op>[a-z][\w.]*)\s*(?P<args>[^\n#/]*)')
_NO_WRITE = ('s', 'b', 'j', 'mtc', 'ctc', 'mult', 'div', 'nop', 'c.', 'break', 'teq', 'trunc')


def _instructions(asm):
    found = []
    for line in asm.splitlines():
        hit = _INSN.match(line)
        if hit and hit['op'] not in ('glabel', 'endlabel'):
            found.append((hit['op'], [part.strip() for part in hit['args'].split(',') if part.strip()]))
    return found


def _writes(op, args, register):
    stores = op in ('sb', 'sh', 'sw', 'sd', 'swl', 'swr', 'swc1', 'sdc1')
    if stores or not args or args[0] != register:
        return False
    return op.startswith(('sll', 'sra', 'srl', 'slt', 'sub', 'seb', 'seh')) or not op.startswith(_NO_WRITE)


def _copied_before_step(instructions, callee, argument, step):
    """Whether the target copies a register into $a<argument>, then steps it by `step`, then calls `callee` with the
    copy still there."""
    wanted = f'$a{argument}'
    for at, (op, args) in enumerate(instructions):
        if op != 'addiu' or len(args) != 3 or args[0] != args[1]:
            continue
        try:
            if int(args[2], 0) != step:
                continue
        except ValueError:
            continue
        register = args[0]
        copied = False
        for before_op, before in reversed(instructions[max(0, at - 8):at]):
            if (before_op in ('move', 'addu', 'daddu', 'or') and before[:2] == [wanted, register]
                    and before[2:] in ([], ['$zero'])):
                copied = True
                break
            if before_op.startswith('jal') or _writes(before_op, before, register) or _writes(before_op, before, wanted):
                break
        if not copied:
            continue
        for later, (after_op, after) in enumerate(instructions[at + 1:at + 24], at + 1):
            if after_op == 'jal':
                slot = instructions[later + 1:later + 2]
                if after[:1] == [callee] and not any(_writes(o, a, wanted) for o, a in slot):
                    return True
                break
            if _writes(after_op, after, wanted):
                break
    return False


def _run_before(clean, opening, position):
    """The step statements right before `position`: [(start, end, name, step)] in source order."""
    steps, end = [], position
    while True:
        text = clean[opening:end].rstrip()
        start = max(text.rfind(';', 0, len(text) - 1), text.rfind('{'), text.rfind('}')) + 1
        hit = _STEP.fullmatch(text[start:].strip())
        if not hit:
            return steps[::-1]
        begin = opening + start + len(text[start:]) - len(text[start:].lstrip())
        name = hit['a'] or hit['b'] or hit['c']
        steps.append((begin, opening + len(text), name, integer(hit['k'] or hit['k2'] or '1')))
        end = opening + start


def _local(clean, opening, end, name):
    return (re.search(rf'(?m)^[ \t]*[A-Za-z_][\w ]*?[ \t*]+{name}[ \t]*;', clean[opening:end])
            and not re.search(rf'(?<!&)&\s*{name}\b', clean[opening:end]))


def variants(source, name, asm=''):
    part = view(source, name)
    if not part or not asm:
        return []
    clean = part.clean
    instructions = _instructions(asm)
    result = []
    for callee in dict.fromkeys(re.findall(rf'(?<![\w.>])({IDENT})\s*\(', part.body)):
        if callee in ('if', 'while', 'for', 'switch', 'sizeof', 'return'):
            continue
        for start, end in calls(part, callee):
            statement = re.compile(rf'(?:{IDENT}\s*=\s*)?{callee}\s*$')
            head = max(clean.rfind(';', 0, start), clean.rfind('{', 0, start), clean.rfind('}', 0, start)) + 1
            lead = clean[head:clean.rfind('(', 0, start)]
            tail = re.match(r'\s*\)\s*;', clean[end:])
            if not tail or not statement.match(lead.strip()):
                continue
            first = head + len(lead) - len(lead.lstrip())
            steps = _run_before(clean, part.opening + 1, first)
            names = [step[2] for step in steps]
            if not steps or len(set(names)) != len(names):
                continue
            inside = clean[start:end]
            arguments = [inside[a:b].strip() for a, b in split_args(inside)]
            read = [(index, step) for index, text in enumerate(arguments[:4]) for step in steps
                    if re.fullmatch(rf'(?:\(\s*\w+\s*\)\s*)?{step[2]}', text)]
            if (not read or any(len(re.findall(rf'\b{step[2]}\b', inside + lead)) != sum(s is step or s == step for _, s in read)
                                for step in steps)
                    or not all(_local(clean, part.opening, part.end, step[2]) for step in steps)
                    or not all(_copied_before_step(instructions, callee, index, step[3]) for index, step in read)):
                continue
            stop = end + tail.end()
            indent = source[source.rfind('\n', 0, first) + 1:first]
            indent = indent if not indent.strip() else ''
            moved = ''.join('\n' + indent + source[a:b] for a, b, _, _ in steps)
            edits = [(stop, stop, moved)]
            for a, b, _, _ in steps:
                line = source.rfind('\n', 0, a) + 1
                if not source[line:a].strip() and source[b:b + 1] == '\n':
                    edits.append((line, b + 1, ''))
                else:
                    edits.append((a, b, ''))
            child = edit(source, edits)
            if (FAMILY, child) not in result:
                result.append((FAMILY, child))
                for _, combined in companions(child, name)[:1]:
                    rejoined = [text for family, text in join_ladders(combined, name) if family == CHAIN]
                    result.append((COMBINED, rejoined[0] if rejoined else combined))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
