"""Turn a customer's option picks into the labels stored on a cart or order."""

from app.core.exceptions import UnprocessableError
from app.schemas.product import OptionChoice, ProductContent, SelectedOption


def selection_of(raw: object) -> list[SelectedOption]:
    if not isinstance(raw, list):
        return []
    chosen: list[SelectedOption] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        label = item.get("label")
        if not isinstance(name, str) or not isinstance(label, str) or not name or not label:
            continue
        swatch = item.get("swatch")
        chosen.append(
            SelectedOption(
                name=name,
                label=label,
                swatch=swatch if isinstance(swatch, str) else "",
            )
        )
    return chosen


def resolve_selection(content: ProductContent, choices: list[OptionChoice]) -> list[SelectedOption]:
    groups = [group for group in content.options if group.name and group.values]
    if not groups:
        if choices:
            raise UnprocessableError("This product has no options")
        return []

    picked: dict[str, str] = {}
    for choice in choices:
        if choice.group_id in picked:
            raise UnprocessableError("Choose one value for each option")
        picked[choice.group_id] = choice.value_id
    if len(picked) != len(groups):
        raise UnprocessableError("Choose one value for each option")

    chosen: list[SelectedOption] = []
    for group in groups:
        value_id = picked.get(group.id)
        value = next((item for item in group.values if item.id == value_id), None)
        if value is None:
            raise UnprocessableError(f"Choose {group.name}")
        chosen.append(SelectedOption(name=group.name, label=value.label, swatch=value.swatch))
    return chosen
