from decomprepair.record_store_run_order import FAMILY, variants

SOURCE = """typedef struct { f32 x, y, z; } Vec3f;
typedef struct { s32 x, y, z; } Vec3i;

f32 probe(Obj *a)
{
    Vec3f top;
    Vec3f bot;
    Vec3i box[2];
    f32 above;
    f32 below;

    bot.z = a->z;
    top.y = a->y + 100000.0f;
    top.z = a->z;
    below = 0.0f;
    above = 0.0f;
    top.x = a->x;
    bot.y = a->y - 100000.0f;
    bot.x = a->x;
    box[0].z = -115;
    box[1].y = 305;
    box[0].x = -115;
    box[1].x = 115;
    box[0].y = 2;
    box[1].z = 115;
    fill(&top, &bot, box);
    return above + below;
}
"""

ORDERED = """    top.x = a->x;
    top.y = a->y + 100000.0f;
    top.z = a->z;
    below = 0.0f;
    above = 0.0f;
    bot.x = a->x;
    bot.y = a->y - 100000.0f;
    bot.z = a->z;
    box[0].x = -115;
    box[0].y = 2;
    box[0].z = -115;
    box[1].x = 115;
    box[1].y = 305;
    box[1].z = 115;
"""


def test_records_are_regrouped_in_declaration_and_member_order():
    # 257 -> 210 on a 438-instruction SN GCC 2.8.1 floor-height test: the prologue's stores matched written this way
    found = [text for family, text in variants(SOURCE, 'probe') if family == FAMILY]
    assert found
    assert ORDERED in found[0]
    assert found[0].count('=') == SOURCE.count('=')
    # the second child keeps the records in the order the run first stores into them (bot first)
    assert any(text.index('bot.x') < text.index('top.x') for text in found[1:])


def test_member_order_comes_from_the_header():
    source = SOURCE.replace('typedef struct { f32 x, y, z; } Vec3f;\ntypedef struct { s32 x, y, z; } Vec3i;\n', '')
    assert not variants(source, 'probe')
    header = 'typedef struct { f32 x, y, z; } Vec3f;\ntypedef struct { s32 x, y, z; } Vec3i;\n'
    assert ORDERED in variants(source, 'probe', header)[0][1]


def test_dependent_or_called_runs_are_left_alone():
    # a right-hand side that reads a record the run writes: the order is part of the program
    assert not variants(SOURCE.replace('top.z = a->z;', 'top.z = bot.z;'), 'probe')
    assert not variants(SOURCE.replace('bot.x = a->x;', 'bot.x = f(a);'), 'probe')
    ordered = SOURCE.split('    bot.z = a->z;')[0] + ORDERED + '    fill(&top' + SOURCE.split('    fill(&top')[1]
    assert not variants(ordered, 'probe')
