# pipeline_scripts/firestore_sanitizer.py
from typing import Any

def sanitize_for_firestore(data: Any) -> Any:
    """
    Recursively fixes data types that Firestore rejects.
    Specifically: Nested arrays (list/tuple inside list/tuple) are converted to strings.

    Google Firestore throws "invalid nested entity" if you try to save
    an array inside another array (e.g., coordinates [[0,1], [1,2]] or bins).

    Args:
        data: The dictionary, list/tuple, or primitive to clean.

    Returns:
        The cleaned data where nested arrays are converted to string representations.
        NOTE: This function does NOT mutate the input in-place; it returns new structures.
    """

    if isinstance(data, dict):
        return {k: sanitize_for_firestore(v) for k, v in data.items()}

    # Treat tuples as arrays too (common in bins/points upstream)
    if isinstance(data, (list, tuple)):
        items = list(data)

        # Check if this array contains other arrays (nested)
        if any(isinstance(item, (list, tuple)) for item in items):
            # Convert only the inner arrays to strings, keep the outer array
            cleaned_list = []
            for item in items:
                if isinstance(item, (list, tuple)):
                    cleaned_list.append(str(list(item)))
                else:
                    cleaned_list.append(sanitize_for_firestore(item))
            return cleaned_list

        # Flat array -> recurse into items (e.g., list of dicts)
        return [sanitize_for_firestore(x) for x in items]

    return data