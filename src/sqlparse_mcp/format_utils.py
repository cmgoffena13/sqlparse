def bullet(text: str, lead: str = "") -> str:
    return f"  {lead}• {text}"


def gutter_width(numbers: list[int]) -> int:
    return max((len(str(number)) for number in numbers), default=1)
