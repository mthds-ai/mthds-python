import re


def is_snake_case(word: str) -> bool:
    return re.match(r"^[a-z][a-z0-9_]*$", word) is not None


def is_pascal_case(word: str) -> bool:
    return re.match(r"^[A-Z][a-zA-Z0-9]*$", word) is not None
