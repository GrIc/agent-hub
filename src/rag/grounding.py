"""
Grounding utilities for anti-hallucination checks.

This module provides:
- GROUNDING_INSTRUCTION: The canonical grounding rules for all documentation generation
- Identifier extraction utilities for Java/Python
- Validation functions to detect hallucinated names
"""

import re
from typing import Set

# Canonical grounding instruction to be used across all agents
GROUNDING_INSTRUCTION = """
ABSOLUTE RULES (mandatory — violations corrupt the entire documentation system):
- ONLY describe classes, methods, variables, and imports that appear VERBATIM in the
  source code above. If a name does not appear in the source, do NOT mention it.
- NEVER infer, extrapolate, or invent functionality. If the source code does not show
  a behavior, do not describe it.
- NEVER add classes, methods, fields, or imports that are not in the source.
- If the code is too complex to fully document from what is visible, write
  "[NOT VISIBLE IN PROVIDED CODE]" for the unclear parts.
- If the module is simple, produce a SHORT document. Do not pad with guesses.
- Every file path you cite must match exactly what appears in the [FILE: ...] headers.
"""

# Noise filter terms - common framework/library terms that appear in docs but not in source
NOISE_FILTER_TERMS = {
    # Java/Spring ecosystem
    "Spring", "JPA", "Hibernate", "Repository", "Controller", "Service", "Entity",
    "Component", "Autowired", "Bean", "REST", "HTTP", "JSON", "XML", "SQL", "CRUD",
    "DTO", "POJO", "DAO", "MVC", "AOP", "ORM", "Maven", "Gradle",
    
    # General programming terms
    "String", "Integer", "Boolean", "Double", "Float", "Long", "Short", "Byte",
    "List", "Array", "Map", "Set", "Queue", "Stack", "Vector", "HashMap", "HashSet",
    "ArrayList", "LinkedList", "Optional", "Stream", "Function", "Consumer", "Supplier",
    "Predicate", "Object", "Class", "Interface", "Method", "Constructor", "Parameter",
    "Variable", "Constant", "Enum", "Exception", "Error", "Runtime", "Thread", "Process",
    
    # Common abbreviations and keywords
    "API", "UI", "UX", "CLI", "DB", "ID", "URL", "URI", "UUID", "JSON", "XML",
    "HTML", "CSS", "JS", "TS", "PHP", "Ruby", "Go", "Rust", "C#", "Kotlin",
    "Scala", "Groovy",
    
    # Framework-specific
    "Lombok", "SLF4J", "Log4j", "JUnit", "Mockito", "Jackson", "Gson", "Tomcat",
    "Jetty", "Netty", "SpringBoot", "SpringMVC", "SpringSecurity", "SpringData",
    "React", "Angular", "Vue", "Django", "Flask", "FastAPI", "Express", "Laravel",
    
    # Database terms
    "Database", "Table", "Column", "Row", "PrimaryKey", "ForeignKey", "Index",
    "Transaction", "Commit", "Rollback", "Query", "Schema", "Migration",
    
    # DevOps/Tools
    "Docker", "Kubernetes", "Git", "GitHub", "GitLab", "Bitbucket", "CI", "CD",
    "Jenkins", "Travis", "CircleCI", "AWS", "Azure", "GCP", "EC2", "S3", "Lambda",
    "Dockerfile", "docker-compose",
}


def extract_identifiers(source_code: str) -> Set[str]:
    """
    Regex-based extractor for Java/Python identifiers.
    
    Returns a set of known identifiers from the source code:
    - Java: class X, interface X, enum X, public ... methodName(
    - Python: class X, def x(
    - General: any CamelCase or snake_case token >= 4 chars
    
    Args:
        source_code: The source code to analyze
        
    Returns:
        Set of identifier strings
    """
    identifiers = set()
    
    # Java/Python class definitions
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
    
    # General identifier pattern: CamelCase or snake_case tokens >= 4 chars
    # This catches many class/method names that might not match the above patterns
    general_pattern = r'\b([A-Z][a-zA-Z0-9_]{3,}|[a-z][a-z0-9_]{3,})\b'
    for match in re.finditer(general_pattern, source_code):
        identifiers.add(match.group(1))
    
    # Remove common noise words that are too generic
    # These are typically keywords or very common terms
    noise_words = {
        'main', 'run', 'test', 'main', 'init', 'new', 'get', 'set', 'is', 'has',
        'for', 'while', 'if', 'else', 'return', 'import', 'from', 'as', 'try',
        'except', 'finally', 'with', 'lambda', 'yield', 'pass', 'break', 'continue',
        'True', 'False', 'None', 'self', 'cls', 'super'
    }
    
    identifiers = identifiers - noise_words
    
    return identifiers


def validate_doc(doc_text: str, known_ids: Set[str]) -> list[str]:
    """
    Scan generated doc for hallucinated names (excluding noise filter terms).
    
    Args:
        doc_text: The generated documentation text
        known_ids: Set of identifiers that exist in the source code
        
    Returns:
        List of hallucinated names found in the doc
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
