"""Use the measured shared argument load to preserve the first store's delay slot."""

from decomprepair.projection_argument_before_store import FAMILY, variants

SOURCE = '''
extern float heading;
extern float first_bias, second_bias;
float project_x(float angle);
float project_y(float angle);
void project(void *output, void *state)
{
    *((float *) (((char *) output) + 4)) = (float) ((first_bias + (*((float *) (((char *) state) + 12)))) + (project_x(heading) * 0.25f));
    *((float *) (((char *) output) + 8)) = (float) ((second_bias + (*((float *) (((char *) state) + 16)))) + (project_y(heading) * 0.25f));
}
'''
HIGH = 'lui $at, %hi(heading)'
LOW = 'lwc1 $f12, %lo(heading)($at)'
STORE = 'swc1 $f2, 4($s2)'
SECOND = 'swc1 $f2, 8($s2)'
CALL = 'jal project_y'
ROWS = [
    (' ', HIGH, HIGH),
    (' ', 'jal project_x', 'jal project_x'),
    (' ', LOW, LOW),
    (' ', 'mul.s $f0, $f0, $f20', 'mul.s $f0, $f0, $f20'),
    (' ', 'add.s $f2, $f2, $f0', 'add.s $f2, $f2, $f0'),
    ('o', '', STORE),
    (' ', HIGH, HIGH),
    ('o', '', CALL),
    (' ', LOW, LOW),
    ('o', CALL, ''),
    ('o', STORE, ''),
    (' ', SECOND, SECOND),
]


def test_captures_the_next_argument_after_the_first_compute_and_before_its_write():
    [(family, candidate)] = variants(SOURCE, 'project', ROWS)
    assert family == FAMILY
    first = candidate.index('project_x(heading) *')
    capture = candidate.index('repair_projection_argument = heading;')
    write = candidate.index('output) + 4)) = repair_projection_value;')
    second = candidate.index('project_y(repair_projection_argument)')
    assert first < capture < write < second


def test_requires_both_projections_and_the_measured_offsets_and_shared_argument():
    assert not variants(SOURCE, 'project', ROWS[2:])
    assert not variants(SOURCE, 'project', ROWS[:-1])
    assert not variants(SOURCE.replace('project_y(heading)', 'project_y(other)'), 'project', ROWS)
    assert not variants(SOURCE.replace('output) + 8', 'output) + 20'), 'project', ROWS)
    assert not variants(SOURCE.replace('output) + 8', 'state) + 8'), 'project', ROWS)
    assert not variants(SOURCE.replace('extern float heading;', 'extern volatile float heading;'), 'project', ROWS)
