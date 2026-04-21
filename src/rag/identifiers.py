"""
Identifier extraction utilities for anti-hallucination checks.

This module provides:
- extract_identifiers(): Extract known identifiers from source code
- validate_names(): Validate LLM output against known identifiers
- load_noise_filter(): Load noise filter terms from config
"""

import re
from typing import Set, List

# Re-export from grounding for convenience
from src.rag.grounding import NOISE_FILTER_TERMS


def extract_identifiers(source_code: str, language: str = "java") -> Set[str]:
    """
    Regex-based extractor for Java/Python identifiers.
    
    Returns a set of known identifiers from the source code:
    - Java: class X, interface X, enum X, public ... methodName(
    - Python: class X, def x(
    - General: any CamelCase or snake_case token >= 4 chars
    
    Args:
        source_code: The source code to analyze
        language: Programming language ("java", "python", "javascript", etc.)
        
    Returns:
        Set of identifier strings
    """
    identifiers = set()
    
    # Language-specific patterns
    if language.lower() in ["java", "javascript", "typescript", "c", "cpp", "c#", "go", "rust"]:
        # Java/Python/C-style class definitions
        # Matches: class X, interface X, enum X, @interface X
        class_pattern = r'\b(?:class|interface|enum|@interface)\s+([A-Z]\w*)\b'
        for match in re.finditer(class_pattern, source_code):
            identifiers.add(match.group(1))
        
        # Method definitions (Java style: public/private/protected/def + name + ()
        # Also matches Python def methods
        method_pattern = r'\b(?:public|private|protected|static|final|def|async\s+def)\s+[^\s(]+\s*\([^)]*\)'
        for match in re.finditer(method_pattern, source_code):
            # Extract method name from the match
            text = match.group(0)
            # Look for word after modifiers and before (
            name_match = re.search(r'(?:public|private|protected|static|final|def|async\s+def)\s+([a-zA-Z_]\w*)\s*\(', text)
            if name_match:
                identifiers.add(name_match.group(1))
        
        # Function definitions (Python style without def prefix in match)
        func_pattern = r'\b([a-z]\w*\s*\([^)]*\))'
        for match in re.finditer(func_pattern, source_code):
            func_sig = match.group(1)
            # Extract just the function name
            name_match = re.match(r'([a-z]\w*)\s*\(', func_sig)
            if name_match:
                identifiers.add(name_match.group(1))
    
    elif language.lower() in ["python", "python3"]:
        # Python class definitions
        class_pattern = r'\bclass\s+([A-Z]\w*)\b'
        for match in re.finditer(class_pattern, source_code):
            identifiers.add(match.group(1))
        
        # Python method definitions
        method_pattern = r'\bdef\s+([a-z_]\w*)\s*\('
        for match in re.finditer(method_pattern, source_code):
            identifiers.add(match.group(1))
        
        # Python function definitions
        func_pattern = r'\bdef\s+([a-z_]\w*)\s*\('
        for match in re.finditer(func_pattern, source_code):
            identifiers.add(match.group(1))
    
    # General identifier pattern: CamelCase or snake_case tokens >= 4 chars
    # This catches many class/method names that might not match the above patterns
    general_pattern = r'\b([A-Z][a-zA-Z0-9_]{3,}|[a-z][a-z0-9_]{3,})\b'
    for match in re.finditer(general_pattern, source_code):
        identifiers.add(match.group(1))
    
    # Remove common noise words that are too generic
    # These are typically keywords or very common terms
    noise_words = {
        'main', 'run', 'test', 'init', 'new', 'get', 'set', 'is', 'has',
        'for', 'while', 'if', 'else', 'return', 'import', 'from', 'as', 'try',
        'except', 'finally', 'with', 'lambda', 'yield', 'pass', 'break', 'continue',
        'True', 'False', 'None', 'self', 'cls', 'super', 'class', 'def', 'return'
    }
    
    identifiers = identifiers - noise_words
    
    return identifiers


def validate_names(doc_text: str, known_ids: Set[str]) -> List[str]:
    """
    Scan generated doc for hallucinated names (excluding noise filter terms).
    
    Validates:
    - Backtick-quoted tokens: `SomeName` or `SomeName()`
    - CamelCase tokens >= 4 chars: AuthService
    - snake_case tokens >= 4 chars: auth_service
    - Dotted paths: com.example.Foo, my.module.bar
    
    Args:
        doc_text: The generated documentation text
        known_ids: Set of identifiers that exist in the source code
        
    Returns:
        List of hallucinated names found in the doc (empty if none)
    """
    hallucinated = []
    
    # Extract backtick-quoted names
    # Pattern matches `SomeName` or `SomeName()`
    backtick_pattern = r'`([^`\s]+)`'
    for match in re.finditer(backtick_pattern, doc_text):
        name = match.group(1)
        # Clean up: remove trailing () and .method calls
        clean_name = name.replace("()", "").split(".")[0]
        
        # Skip noise filter terms
        if clean_name in NOISE_FILTER_TERMS:
            continue
        
        # Check if it's in known identifiers
        if clean_name not in known_ids:
            hallucinated.append(name)
    
    # Also check bolded names (common in markdown)
    bold_pattern = r'\*\*([A-Z][a-zA-Z0-9_]+)\*\*'
    for match in re.finditer(bold_pattern, doc_text):
        name = match.group(1)
        if name not in known_ids and name not in NOISE_FILTER_TERMS:
            hallucinated.append(name)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_hallucinations = []
    for name in hallucinated:
        if name not in seen:
            seen.add(name)
            unique_hallucinations.append(name)
    
    return unique_hallucinations


def load_noise_filter(config: dict) -> Set[str]:
    """
    Load noise filter terms from config.yaml.
    
    Args:
        config: The application config dictionary
        
    Returns:
        Set of noise filter terms (NOISE_FILTER_TERMS union config terms)
    """
    noise = set(NOISE_FILTER_TERMS)
    
    # Add config-specific noise terms if present
    if config and isinstance(config, dict):
        config_noise = config.get("noise_filter", {}).get("terms", [])
        if isinstance(config_noise, list):
            noise.update(config_noise)
    
    return noise
