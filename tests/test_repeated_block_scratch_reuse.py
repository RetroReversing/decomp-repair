"""Per-axis locals of three repeated blocks written as one scratch variable per role, and the derived values stored where
they are computed."""
from decomprepair import registry
from decomprepair.repeated_block_scratch_reuse import DIRECT_FAMILY, FAMILY, ROLE_FAMILY, variants

DRAFT = '''void spline_setup(const f32 *p, const f32 *q, const f32 *r, const f32 *s, s32 n, Segment *out)
{
    f32 h = 1.0f / (f32)n;
    f32 h2 = h * h;
    f32 h3 = h * h2;
    f32 ax, bx, cx, ay, by, cy, az, bz, cz, dx, ddx, dddx, dy, ddy, dddy, dz, ddz, dddz;
    ax = (p[0] * -0.5f + q[0] * 1.5f - r[0] * 1.5f + s[0] * 0.5f) * h3;
    bx = (p[0] - q[0] * 2.5f + r[0] * 2.0f - s[0] * 0.5f) * h2;
    cx = (p[0] * -0.5f + r[0] * 0.5f) * h;
    dx = ax + bx + cx;
    dddx = ax * 6.0f;
    ddx = dddx + bx * 2.0f;
    ay = (p[1] * -0.5f + q[1] * 1.5f - r[1] * 1.5f + s[1] * 0.5f) * h3;
    by = (p[1] - q[1] * 2.5f + r[1] * 2.0f - s[1] * 0.5f) * h2;
    cy = (p[1] * -0.5f + r[1] * 0.5f) * h;
    dy = ay + by + cy;
    dddy = ay * 6.0f;
    ddy = dddy + by * 2.0f;
    az = (p[2] * -0.5f + q[2] * 1.5f - r[2] * 1.5f + s[2] * 0.5f) * h3;
    bz = (p[2] - q[2] * 2.5f + r[2] * 2.0f - s[2] * 0.5f) * h2;
    cz = (p[2] * -0.5f + r[2] * 0.5f) * h;
    dz = az + bz + cz;
    dddz = az * 6.0f;
    ddz = dddz + bz * 2.0f;
    out->n = n;
    out->x = q[0];
    out->dx = dx;
    out->ddx = ddx;
    out->dddx = dddx;
    out->y = q[1];
    out->dy = dy;
    out->ddy = ddy;
    out->dddy = dddy;
    out->z = q[2];
    out->dz = dz;
    out->ddz = ddz;
    out->dddz = dddz;
}
'''


def by_family(source, name='spline_setup'):
    found = {}
    for family, text in variants(source, name):
        found.setdefault(family, []).append(text)
    return found


def test_the_three_roles_are_merged_at_once_into_scratch_variables_named_by_the_role():
    merged = by_family(DRAFT)[FAMILY][0]
    assert 'f32 a, b, c, dx, ddx, dddx, dy, ddy, dddy, dz, ddz, dddz;' in merged
    assert merged.count('    a = (p[') == 3 and merged.count('    b = (p[') == 3 and merged.count('    c = (p[') == 3
    assert 'dx = a + b + c;' in merged and 'ddz = dddz + b * 2.0f;' in merged
    for gone in ('ax', 'bx', 'cx', 'ay', 'by', 'cy', 'az', 'bz', 'cz'):
        assert f' {gone} ' not in merged and f'({gone}' not in merged
    # nothing else moved: the output locals are written at the end exactly as before
    assert merged.endswith(DRAFT[DRAFT.index('    out->n = n;'):])


def test_the_direct_child_stores_each_derived_value_where_it_is_computed_and_drops_the_locals():
    direct = by_family(DRAFT)[DIRECT_FAMILY][0]
    assert 'f32 a, b, c;' in direct
    assert '    out->dx = a + b + c;\n    out->dddx = a * 6.0f;\n    out->ddx = (a * 6.0f) + b * 2.0f;\n' in direct
    assert '    out->ddz = (a * 6.0f) + b * 2.0f;\n    out->n = n;\n    out->x = q[0];\n    out->y = q[1];\n    out->z = q[2];\n}' in direct
    assert 'dddx = ' not in direct.replace('out->dddx = ', '')


def test_a_role_alone_is_offered_when_there_are_several():
    roles = by_family(DRAFT)[ROLE_FAMILY]
    assert len(roles) == 3
    assert 'ax' not in roles[0] and ' bx ' in roles[0] and ' cx ' in roles[0]


def test_members_whose_mentions_overlap_are_not_merged():
    overlapping = DRAFT.replace('    dy = ay + by + cy;', '    dy = ay + by + cy + ax;')
    merged = by_family(overlapping)
    assert 'ax' in merged[FAMILY][0]  # ax is read after ay is assigned: the role {ax, ay, az} stays split
    assert ' ay ' in merged[FAMILY][0] and 'b = (p[1]' in merged[FAMILY][0]


def test_a_member_that_reads_itself_first_is_not_merged():
    assert variants(DRAFT.replace('ay = (p[1]', 'ay = ay + (p[1]').replace('by = (p[1]', 'by = by + (p[1]')
                    .replace('cy = (p[1]', 'cy = cy + (p[1]'), 'spline_setup') == []


def test_a_function_with_a_loop_or_volatile_is_left_alone():
    looped = DRAFT.replace('    out->n = n;', '    while (n--) { dx += 1.0f; }\n    out->n = n;')
    assert variants(looped, 'spline_setup') == []
    assert variants(DRAFT.replace('Segment *out', 'volatile Segment *out'), 'spline_setup') == []


def test_integer_roles_and_m2c_suffixes_merge_too():
    source = '''s32 total(s32 *v)
{
    s32 acc, acc_2, acc_3;
    acc = v[0] + v[1];
    v[4] = acc;
    acc_2 = v[2] + v[3];
    v[5] = acc_2;
    acc_3 = v[0] + v[3];
    v[6] = acc_3;
    return 0;
}
'''
    merged = by_family(source, 'total')[FAMILY][0]
    assert 's32 acc;' in merged and 'acc_2' not in merged and 'acc_3' not in merged
    assert merged.count('acc = ') == 3


def test_a_stored_local_that_is_read_after_its_operands_change_keeps_its_local():
    source = DRAFT.replace('    ddx = dddx + bx * 2.0f;', '    ax = 2.0f;\n    ddx = dddx + bx * 2.0f;')
    direct = by_family(source).get(DIRECT_FAMILY, [''])[0]
    assert 'dddx = a * 6.0f;' in direct  # dddx is read after `ax` changed: stays a local


def test_the_module_declares_itself_to_the_registry():
    assert 'repeated_block_scratch_reuse' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'repeated_block_scratch_reuse':
            assert registry.problems(repair) == []


def test_a_draft_with_the_pair_in_the_other_order_and_a_volatile_output_reaches_the_plain_blocks():
    """The three steps of the measured match, each from the previous child: the output pointer plain, the roles merged
    with the stores written where the values are computed, then the pair `b`/`a` in every block put the other way round
    (8465 saved best -> 12706 for the merge alone with the pair reversed -> exact once reversed back)."""
    from decomprepair import repeated_block_order_swap, volatile_output_parameter_plain
    draft = DRAFT.replace('Segment *out', 'volatile Segment *out')
    for axis, name in enumerate('xyz'):
        first = f'    a{name} = (p[{axis}] * -0.5f + q[{axis}] * 1.5f - r[{axis}] * 1.5f + s[{axis}] * 0.5f) * h3;\n'
        second = f'    b{name} = (p[{axis}] - q[{axis}] * 2.5f + r[{axis}] * 2.0f - s[{axis}] * 0.5f) * h2;\n'
        assert first + second in draft
        draft = draft.replace(first + second, second + first)
    [(_, plain)] = volatile_output_parameter_plain.variants(draft, 'spline_setup')
    direct = by_family(plain)[DIRECT_FAMILY][0]
    assert direct.index('    b = (p[0]') < direct.index('    a = (p[0]')
    swapped = [text for family, text in repeated_block_order_swap.variants(direct, 'spline_setup')
               if family == repeated_block_order_swap.FAMILY]
    exact = by_family(DRAFT)[DIRECT_FAMILY][0]
    assert exact in swapped
