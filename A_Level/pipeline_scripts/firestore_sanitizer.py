# pipeline_scripts/firestore_sanitizer.py
from typing import Any, Dict, List

def sanitize_for_firestore(data: Any) -> Any:
    """
    Recursively fixes data types that Firestore rejects.
    Specifically: Nested lists (arrays of arrays) are converted to strings.
    
    Google Firestore crashes with 'invalid nested entity' if you try to save
    a list inside another list (e.g., coordinates [[0,1], [1,2]] or bins).
    
    Args:
        data: The dictionary, list, or primitive to clean.
        
    Returns:
        The cleaned data where nested lists are converted to string representations.
    """
    if isinstance(data, dict):
        return {k: sanitize_for_firestore(v) for k, v in data.items()}
    
    elif isinstance(data, list):
        # Check if this list contains other lists (nested)
        if any(isinstance(item, list) for item in data):
            # Option A: Convert the inner lists to strings, keeping the outer list.
            # [[1,2], [3,4]] -> ["[1,2]", "[3,4]"]
            # This is often safer for preserving structure than stringifying the whole blob.
            cleaned_list = []
            for item in data:
                if isinstance(item, list):
                    cleaned_list.append(str(item))
                else:
                    cleaned_list.append(sanitize_for_firestore(item))
            return cleaned_list
        else:
            # It's a flat list (e.g. [1, 2, 3]) -> Process items recursively just in case (e.g. list of dicts)
            return [sanitize_for_firestore(x) for x in data]
            
    else:
        return data