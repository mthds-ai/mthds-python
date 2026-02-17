import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, cast

CLEAN_JSON_FIELDS_TO_SKIP = ("__class__", "__module__")


def clean_json_content(content: Any) -> Any:
    """Recursively clean content for standard JSON serialization.

    Removes kajson metadata fields (``__class__``, ``__module__``) and converts
    non-JSON-native types to their JSON-safe equivalents:

    - ``datetime.datetime`` / ``datetime.date`` / ``datetime.time`` -> ISO-format string
    - ``Enum`` -> its ``.value``
    - ``Decimal`` -> ``float``
    - ``Path`` -> ``str``

    Args:
        content: The data structure to clean (dict, list, or scalar value).

    Returns:
        A cleaned copy of *content* that ``json.dumps`` can serialize directly.
    """
    if isinstance(content, dict):
        cleaned: dict[str, Any] = {}
        content_dict = cast("dict[str, Any]", content)
        for key in content_dict:
            if key in CLEAN_JSON_FIELDS_TO_SKIP:
                continue
            cleaned[key] = clean_json_content(content_dict[key])
        return cleaned
    elif isinstance(content, list):
        content_list = cast("list[Any]", content)
        return [clean_json_content(item) for item in content_list]
    elif isinstance(content, (datetime.datetime, datetime.date, datetime.time)):
        return content.isoformat()
    elif isinstance(content, Enum):
        return content.value
    elif isinstance(content, Decimal):
        return float(content)
    elif isinstance(content, Path):
        return str(content)
    else:
        return content
