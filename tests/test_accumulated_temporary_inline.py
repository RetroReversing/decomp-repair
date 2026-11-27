"""A value built up in a local over two statements, written whole at each place it is read."""
from decomprepair import accumulated_temporary_inline as p
from decomprepair import registry

SOURCE = '''typedef unsigned short u16;
typedef int s32;
s32 rand(void);
s32 sine(s32);

void spawn(s32 *out)
{
    s32 raw;
    s32 speed;
    s32 angle;

    if (out[0] == 0) {
        raw = rand();
        angle = rand() >> 3;
        speed = ((u32) (raw & 0xFFFF) >> 6); speed += 0x733;
        out[1] = (sine(angle) * speed) >> 10;
        out[2] = (sine(angle + 1) * speed) >> 10;
    }
}
'''


def test_the_built_up_value_is_written_at_every_read():
    [(family, child)] = p.variants(SOURCE, 'spawn')
    assert family == p.FAMILY
    expression = '((s32) ((((u32) (raw & 0xFFFF) >> 6)) + 0x733))'
    assert child.count(expression) == 2
    assert 'speed' not in child


def test_a_right_shift_reads_the_value_as_the_local_holds_it():
    [(_, child)] = p.variants(SOURCE.replace('speed += 0x733;', 'speed >>= 2;'), 'spawn')
    assert '((s32) (((s32) (((u32) (raw & 0xFFFF) >> 6))) >> 2))' in child


def test_declined_when_the_value_could_differ_where_it_is_read():
    changed = SOURCE.replace('out[2] =', 'raw = 0;\n        out[2] =')
    memory = SOURCE.replace('(raw & 0xFFFF)', '(out[3] & 0xFFFF)')
    call = SOURCE.replace('(raw & 0xFFFF)', '(rand() & 0xFFFF)')
    later = SOURCE.replace('    }\n}', '    }\n    out[3] = speed;\n}')
    reassigned = SOURCE.replace('out[2] =', 'speed += 1;\n        out[2] =')
    address = SOURCE.replace('angle = rand() >> 3;', 'angle = rand() >> 3;\n        sine((s32) &raw);')
    label = SOURCE.replace('out[2] =', 'again:\n        out[2] =')
    for source in (changed, memory, call, later, reassigned, address, label):
        assert p.variants(source, 'spawn') == [], source


def test_a_single_assignment_is_left_to_single_use_inline():
    assert p.variants(SOURCE.replace(' speed += 0x733;', ''), 'spawn') == []


def test_the_module_declares_itself():
    assert any(repair.module == 'accumulated_temporary_inline' for repair in registry.declared())
