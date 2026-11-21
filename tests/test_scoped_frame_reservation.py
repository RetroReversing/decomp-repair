import pytest

from decomprepair.measured_layout_repairs import scoped_frame_array
from decomprepair.mips_stack import repair_layout

SOURCE = '''void f(void) {
    short value;
    value = 5;
    enqueue(7, &value);
}
'''
TARGET = ('addiu $sp, $sp, -40|addiu $a1, $sp, 16|sw $ra, 32($sp)|jal enqueue|'
          'sh $v0, 16($sp)|lw $ra, 32($sp)|jr $ra|addiu $sp, $sp, 40')
CANDIDATE = 'addiu $sp, $sp, -32|addiu $a1, $sp, 16|sw $ra, 24($sp)|jal enqueue|' \
            'sh $v0, 16($sp)|lw $ra, 24($sp)|jr $ra|addiu $sp, $sp, 32'


def compare(target=TARGET, candidate=CANDIDATE):
    return [(' ' if a == b else 's', a, b) for a, b in zip(target.split('|'), candidate.split('|'))]


def test_scoped_reservation_preserves_escaped_scalar_and_call():
    rows = compare()
    candidate = scoped_frame_array(SOURCE, 'f', rows, repair_layout(rows))
    assert candidate.startswith(SOURCE.removesuffix('}\n'))
    assert 'enqueue(7, &value);\n    {\n' in candidate
    assert 'char __repair_stack_padding[8];' in candidate
    assert scoped_frame_array(candidate, 'f', rows, repair_layout(rows)) is None


@pytest.mark.parametrize('source', [
    SOURCE.replace('&value', 'value'),
    SOURCE.replace('enqueue(7, &value);', 'enqueue(&value, 7);'),
    SOURCE.replace('enqueue(7, &value);', 'if (value) { enqueue(7, &value); }'),
    SOURCE.replace('enqueue(7, &value);', 'enqueue(7, &value);\n    finish();'),
])
def test_requires_final_outer_call_with_unchanged_stack_argument(source):
    rows = compare()
    assert scoped_frame_array(source, 'f', rows, repair_layout(rows)) is None


@pytest.mark.parametrize(('target', 'candidate'), [
    (TARGET, CANDIDATE.replace('sh $v0, 16', 'sh $v0, 18')),
    (TARGET.replace('jal enqueue', 'move $a1, $zero|jal enqueue'),
     CANDIDATE.replace('jal enqueue', 'move $a1, $zero|jal enqueue')),
])
def test_rejects_changed_local_offsets_or_overwritten_argument(target, candidate):
    rows = compare(target, candidate)
    assert scoped_frame_array(SOURCE, 'f', rows, repair_layout(rows)) is None
