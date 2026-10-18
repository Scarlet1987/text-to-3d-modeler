"""Rough visual: 2D technical drawing from verified spec dimensions.

Takes the verified spec and draws it to scale as SVG — instant feedback
on whether the dimensions make sense, before the slow CAD build.
No AI image gen, no guessing: just the numbers, drawn accurately.
"""

from __future__ import annotations

from agent.spec import BuildSpec


def spec_to_svg(spec: BuildSpec, width_px: int = 400, height_px: int = 300) -> str:
    """Draw the spec's footprint and features as a scaled SVG."""
    dims = {d.label: d.value_mm for d in spec.verified_dimensions()}
    if not dims:
        return _empty_svg("no verified dimensions")

    # Find the two largest dimensions for the footprint.
    sorted_dims = sorted(
        [(d.label, d.value_mm) for d in spec.verified_dimensions()],
        key=lambda x: x[1], reverse=True,
    )
    if len(sorted_dims) < 2:
        return _empty_svg("need at least 2 dimensions for a drawing")

    label_w, w_mm = sorted_dims[0]
    label_h, h_mm = sorted_dims[1]

    # Scale to fit with margin.
    margin = 30
    scale = min((width_px - 2 * margin) / w_mm, (height_px - 2 * margin) / h_mm)
    w_px, h_px = w_mm * scale, h_mm * scale
    x0, y0 = (width_px - w_px) / 2, (height_px - h_px) / 2

    parts = [
        f'<svg width="{width_px}" height="{height_px}" xmlns="http://www.w3.org/2000/svg" '
        f'style="background:#0c1414;border-radius:8px">',
        # Footprint rectangle.
        f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w_px:.1f}" height="{h_px:.1f}" '
        f'fill="none" stroke="#2dd4bf" stroke-width="2"/>',
        # Dimension labels.
        f'<text x="{width_px/2:.0f}" y="{y0 - 8:.0f}" fill="#8aa5a5" font-size="12" '
        f'text-anchor="middle">{w_mm}mm ({label_w})</text>',
        f'<text x="{x0 - 8:.0f}" y="{height_px/2:.0f}" fill="#8aa5a5" font-size="12" '
        f'text-anchor="end" transform="rotate(-90,{x0 - 8:.0f},{height_px/2:.0f})">'
        f'{h_mm}mm ({label_h})</text>',
    ]

    # Draw mounting holes if inset info is available.
    hole_dia = dims.get("hole diameter")
    inset = dims.get("inset")
    if hole_dia and inset:
        r_px = (hole_dia / 2) * scale
        ix, iy = inset * scale, inset * scale
        for hx, hy in [
            (x0 + ix, y0 + iy), (x0 + w_px - ix, y0 + iy),
            (x0 + ix, y0 + h_px - iy), (x0 + w_px - ix, y0 + h_px - iy),
        ]:
            parts.append(
                f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="{r_px:.1f}" '
                f'fill="none" stroke="#e08080" stroke-width="1.5"/>'
            )
            parts.append(
                f'<line x1="{hx - r_px - 3:.1f}" y1="{hy:.1f}" x2="{hx + r_px + 3:.1f}" y2="{hy:.1f}" '
                f'stroke="#e08080" stroke-width="0.5"/>'
            )
            parts.append(
                f'<line x1="{hx:.1f}" y1="{hy - r_px - 3:.1f}" x2="{hx:.1f}" y2="{hy + r_px + 3:.1f}" '
                f'stroke="#e08080" stroke-width="0.5"/>'
            )

    # Title.
    parts.append(
        f'<text x="{width_px/2:.0f}" y="{height_px - 8:.0f}" fill="#8aa5a5" font-size="11" '
        f'text-anchor="middle">{spec.part_name or "part"} — top view, to scale</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def _empty_svg(message: str) -> str:
    return (
        '<svg width="400" height="300" xmlns="http://www.w3.org/2000/svg" '
        'style="background:#0c1414;border-radius:8px">'
        f'<text x="200" y="150" fill="#8aa5a5" font-size="13" text-anchor="middle">{message}</text>'
        "</svg>"
    )
