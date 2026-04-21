import re

# Test the regex directly
pattern = re.compile(r'\bclass\s+([A-Z][A-Za-z0-9_]+)')
src = 'class Foo { } class Bar { } interface Baz { } enum Qux { }'
matches = list(pattern.finditer(src))
print('Matches:', [(m.group(0), m.group(1)) for m in matches])
print('Extracted:', [m.group(1) for m in matches])

# Test with findall
pattern2 = re.compile(r'\bclass\s+([A-Z][A-Za-z0-9_]+)')
print('Findall:', pattern2.findall(src))
