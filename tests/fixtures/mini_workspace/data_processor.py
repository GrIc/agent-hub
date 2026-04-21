"""Data processing utilities.

This is a synthetic file for testing grounding.
"""

from typing import List, Dict, Any
import json


def process_data(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Process a list of data items.
    
    Args:
        items: List of dictionaries to process
        
    Returns:
        Processed result
    """
    result = {"count": len(items), "items": []}
    for item in items:
        processed = {
            "id": item.get("id"),
            "name": item.get("name"),
            "value": item.get("value", 0)
        }
        result["items"].append(processed)
    return result


def load_config(filename: str) -> Dict[str, Any]:
    """Load configuration from JSON file.
    
    Args:
        filename: Path to JSON config file
        
    Returns:
        Configuration dictionary
    """
    with open(filename, "r") as f:
        return json.load(f)


def save_result(data: Dict[str, Any], output_file: str) -> None:
    """Save result to JSON file.
    
    Args:
        data: Data to save
        output_file: Path to output file
    """
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)
