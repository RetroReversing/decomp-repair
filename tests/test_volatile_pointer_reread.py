"""A volatile global pointer read through the global again, where the target reads it once into the local it stores through."""
from decomprepair import registry
from decomprepair import volatile_pointer_reread as p

SOURCE = '''typedef float f32;
typedef struct { char pad[0x12C]; f32 field_12C; } Marker;
extern void *volatile gMarker;
#define MARKER (*(void **) &gMarker)
extern void tick(void);

void step(int mode)
{
    Marker *marker;
    f32 temp;
    switch (mode) {
    case 1:
        marker = MARKER;
        marker->field_12C = (f32) (marker->field_12C - 0.5f);
        temp = ((Marker *) (gMarker))->field_12C;
        if (temp < 0.0f) {
            marker->field_12C = 0.0f;
            tick();
        }
        break;
    case 2:
        marker = gMarker;
        do {
            if (((temp = ((Marker *) (gMarker))->field_12C) <= 0.0f) || (temp >= 1.0f)) {
                marker->field_12C = 1.0f;
            }
        } while (0);
        break;
    }
}
'''


def texts(source=SOURCE, header=''):
    return [text for _, text in p.variants(source, 'step', header)]


def test_a_second_volatile_read_is_made_into_the_local_the_store_uses():
    """The track marker's countdown (535 -> 320 alone): the local takes the second read, the store goes through it."""
    assert any('marker = gMarker;temp = marker->field_12C;' in t for t in texts())


def test_a_read_right_after_the_assignment_folds_into_the_local():
    """The same read inside a condition (300 -> 60 with the split): the volatile global is read once, not twice."""
    assert any('if (((temp = marker->field_12C) <= 0.0f) || (temp >= 1.0f))' in t for t in texts())


def test_every_site_at_once_is_one_child():
    both = [t for t in texts() if 'marker = gMarker;temp = marker->field_12C;' in t and 'temp = marker->field_12C) <= 0.0f' in t]
    assert len(both) == 1 and '((Marker *) (gMarker))' not in both[0]


def test_the_volatile_declaration_may_come_from_the_header():
    header = 'extern void *volatile gMarker;\n'
    source = SOURCE.replace('extern void *volatile gMarker;\n', 'extern void *gMarker;\n')
    assert texts(source, header) and not texts(source)


def test_a_global_that_is_not_volatile_is_left_alone():
    assert texts(SOURCE.replace('extern void *volatile gMarker;', 'extern void *gMarker;')) == []


def test_a_read_nothing_uses_afterwards_is_not_assigned_to_the_local():
    source = SOURCE.replace('            marker->field_12C = 0.0f;\n', '            tick();\n').replace('                marker->field_12C = 1.0f;\n', '                tick();\n')
    assert not any('marker = gMarker;temp = marker->field_12C;' in t for t in texts(source))


def test_a_read_that_follows_another_write_of_the_local_does_not_fold():
    source = SOURCE.replace('        marker = gMarker;\n        do', '        marker = gMarker;\n        marker = MARKER;\n        do')
    assert not any('temp = marker->field_12C) <= 0.0f' in t for t in texts(source))


def test_a_loop_header_read_is_not_moved():
    source = SOURCE.replace('        break;\n    }\n}', '        break;\n    }\n    for (; ((Marker *) (gMarker))->field_12C < 1.0f;) {\n        marker->field_12C = 1.0f;\n    }\n}')
    assert not any('for (; marker' in t for t in texts(source))


def test_it_is_declared_for_every_caller():
    repair = registry.get('volatile_pointer_reread')
    assert repair and registry.problems(repair) == [] and 'header' in repair.needs
