"""Pure geometry helpers shared by Cut3D's viewport and build engines.

This module intentionally has no Blender dependency.  Keeping stroke cleanup
and profile evaluation here makes the behaviour testable outside Blender and
prevents the preview and the final cutter from interpreting the same gesture
in different ways.
"""

import math


def _distance_to_segment(point, start, end):
    dimensions = min(len(point), len(start), len(end))
    delta = [end[index] - start[index] for index in range(dimensions)]
    length_sq = sum(value * value for value in delta)
    if length_sq <= 1e-20:
        return math.sqrt(sum(
            (point[index] - start[index]) ** 2 for index in range(dimensions)
        ))
    factor = sum(
        (point[index] - start[index]) * delta[index]
        for index in range(dimensions)
    ) / length_sq
    factor = max(0.0, min(1.0, factor))
    return math.sqrt(sum(
        (point[index] - (start[index] + delta[index] * factor)) ** 2
        for index in range(dimensions)
    ))


def simplify_polyline(points, tolerance):
    """Iterative Ramer-Douglas-Peucker simplification for 2D/3D tuples."""
    if len(points) <= 2 or tolerance <= 0.0:
        return list(points)
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        greatest = tolerance
        greatest_index = None
        for index in range(first + 1, last):
            distance = _distance_to_segment(points[index], points[first], points[last])
            if distance > greatest:
                greatest = distance
                greatest_index = index
        if greatest_index is not None:
            keep.add(greatest_index)
            stack.append((first, greatest_index))
            stack.append((greatest_index, last))
    return [points[index] for index in sorted(keep)]


def monotonic_profile(points, min_step=1e-8):
    """Return an ordered x/z profile without allowing the stroke to fold back.

    A Fruit-Ninja gesture has one dominant direction.  Tiny backwards motion
    from hand jitter is folded into the latest sample instead of sorting every
    point by X (sorting destroys intentional curve order and creates spikes).
    """
    if len(points) < 2:
        return list(points)
    result = [list(points[0])]
    for point in points[1:]:
        x, z = float(point[0]), float(point[1])
        previous_x = result[-1][0]
        if x > previous_x + min_step:
            result.append([x, z])
        elif len(result) == 1:
            result[0][1] = z
        else:
            # Keep the farthest progress but update its height, which smooths
            # small mouse reversals without rearranging the stroke.
            result[-1][1] = (result[-1][1] + z) * 0.5
    if len(result) == 1:
        result.append([float(points[-1][0]), float(points[-1][1])])
    return result


def profile_value(profile, x):
    """Linearly evaluate a canonical monotonic x/z profile."""
    if not profile:
        return 0.0
    if x <= profile[0][0]:
        return profile[0][1]
    if x >= profile[-1][0]:
        return profile[-1][1]
    low = 0
    high = len(profile) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if profile[middle][0] <= x:
            low = middle
        else:
            high = middle
    first, second = profile[low], profile[high]
    span = second[0] - first[0]
    if abs(span) <= 1e-20:
        return first[1]
    factor = (x - first[0]) / span
    return first[1] + (second[1] - first[1]) * factor


def expanded_profile(profile, margin):
    """Extend both ends while preserving their local tangent height."""
    if len(profile) < 2:
        return list(profile)
    margin = max(float(margin), 0.0)
    return [
        [profile[0][0] - margin, profile[0][1]],
        *[list(point) for point in profile],
        [profile[-1][0] + margin, profile[-1][1]],
    ]


def signed_profile_distance(profile, point):
    """Signed height of an x/y/z point relative to the cut profile."""
    return float(point[2]) - profile_value(profile, float(point[0]))


def resample_polyline(points, count):
    """Return ``count`` evenly spaced samples along an N-dimensional polyline."""
    points = [list(map(float, point)) for point in points]
    count = max(2, int(count))
    if len(points) < 2:
        return points
    lengths = [0.0]
    for first, second in zip(points, points[1:]):
        dimensions = min(len(first), len(second))
        length = math.sqrt(sum(
            (second[index] - first[index]) ** 2 for index in range(dimensions)
        ))
        lengths.append(lengths[-1] + length)
    total = lengths[-1]
    if total <= 1e-20:
        return [points[0][:] for _index in range(count)]
    result = []
    segment = 0
    for index in range(count):
        target = total * index / (count - 1)
        while segment + 1 < len(lengths) - 1 and lengths[segment + 1] < target:
            segment += 1
        start, end = points[segment], points[segment + 1]
        span = lengths[segment + 1] - lengths[segment]
        factor = 0.0 if span <= 1e-20 else (target - lengths[segment]) / span
        dimensions = min(len(start), len(end))
        result.append([
            start[axis] + (end[axis] - start[axis]) * factor
            for axis in range(dimensions)
        ])
    return result


def catmull_rom_polyline(points, subdivisions=6):
    """Smooth an open control polyline while keeping every control point."""
    points = [list(map(float, point)) for point in points]
    if len(points) < 3 or subdivisions <= 1:
        return points
    dimensions = min(len(point) for point in points)
    result = []
    for index in range(len(points) - 1):
        p0 = points[index - 1] if index > 0 else points[index]
        p1 = points[index]
        p2 = points[index + 1]
        p3 = points[index + 2] if index + 2 < len(points) else points[index + 1]
        for step in range(subdivisions):
            factor = step / subdivisions
            factor_sq = factor * factor
            factor_cube = factor_sq * factor
            result.append([
                0.5 * (
                    2.0 * p1[axis]
                    + (-p0[axis] + p2[axis]) * factor
                    + (2.0 * p0[axis] - 5.0 * p1[axis] + 4.0 * p2[axis] - p3[axis]) * factor_sq
                    + (-p0[axis] + 3.0 * p1[axis] - 3.0 * p2[axis] + p3[axis]) * factor_cube
                )
                for axis in range(dimensions)
            ])
    result.append(points[-1][:dimensions])
    return result


def rail_value_at_x(rail, x):
    """Interpolate an ordered 3D rail at X, returning ``[x, y, z]``."""
    if not rail:
        return [float(x), 0.0, 0.0]
    ordered = sorted((list(map(float, point[:3])) for point in rail), key=lambda point: point[0])
    if x <= ordered[0][0]:
        return [float(x), ordered[0][1], ordered[0][2]]
    if x >= ordered[-1][0]:
        return [float(x), ordered[-1][1], ordered[-1][2]]
    low = 0
    high = len(ordered) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if ordered[middle][0] <= x:
            low = middle
        else:
            high = middle
    first, second = ordered[low], ordered[high]
    span = second[0] - first[0]
    factor = 0.0 if abs(span) <= 1e-20 else (x - first[0]) / span
    return [
        float(x),
        first[1] + (second[1] - first[1]) * factor,
        first[2] + (second[2] - first[2]) * factor,
    ]


def surface_height(front, back, point):
    """Evaluate the ruled cutting surface between editable front/back rails."""
    x, y = float(point[0]), float(point[1])
    front_point = rail_value_at_x(front, x)
    back_point = rail_value_at_x(back, x)
    span = back_point[1] - front_point[1]
    factor = 0.5 if abs(span) <= 1e-20 else (y - front_point[1]) / span
    factor = max(0.0, min(1.0, factor))
    return front_point[2] + (back_point[2] - front_point[2]) * factor


def signed_surface_distance(front, back, point):
    """Signed Z distance from a point to an editable ruled surface."""
    return float(point[2]) - surface_height(front, back, point)
