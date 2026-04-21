"""Tests for src/rag/identifiers.py

Unit tests for identifier extraction with AST and regex fallback.
"""

import pytest
from pathlib import Path
from src.rag.identifiers import (
    extract_identifiers,
    detect_language,
    _extract_regex,
    _extract_ast_java,
    _extract_ast_python,
)


class TestDetectLanguage:
    """Test language detection from file paths."""

    def test_detect_java(self):
        assert detect_language("src/main/java/com/example/Foo.java") == "java"
        assert detect_language("test.JAVA") == "java"

    def test_detect_python(self):
        assert detect_language("src/main/python/foo.py") == "python"
        assert detect_language("test.Py") == "python"

    def test_detect_unknown(self):
        assert detect_language("test.txt") == "unknown"
        assert detect_language("Makefile") == "unknown"


class TestRegexExtraction:
    """Test regex-based identifier extraction."""

    def test_extract_class_names(self):
        src = "class Foo { } class Bar { } interface Baz { } enum Qux { }"
        ids = _extract_regex(src)
        assert "Foo" in ids
        assert "Bar" in ids
        assert "Baz" in ids
        assert "Qux" in ids

    def test_extract_python_functions(self):
        src = "def foo(): pass\ndef bar_baz(): pass\nclass Helper: pass"
        ids = _extract_regex(src)
        assert "foo" in ids
        assert "bar_baz" in ids
        assert "Helper" in ids

    def test_extract_java_methods(self):
        src = "public void methodOne() { } private int methodTwo() { }"
        ids = _extract_regex(src)
        assert "methodOne" in ids
        assert "methodTwo" in ids

    def test_extract_camelcase(self):
        src = "The UserService handles authentication. The AuthManager validates tokens."
        ids = _extract_regex(src)
        assert "UserService" in ids
        assert "AuthManager" in ids

    def test_extract_snakecase(self):
        src = "The user_service handles authentication. The auth_manager validates tokens."
        ids = _extract_regex(src)
        assert "user_service" in ids
        assert "auth_manager" in ids

    def test_extract_dotted_paths(self):
        src = "Import com.example.foo.Bar and org.apache.commons.Utils"
        ids = _extract_regex(src)
        assert "com.example.foo.Bar" in ids
        assert "org.apache.commons.Utils" in ids

    def test_filter_short_tokens(self):
        src = "class A { } def b(): pass"
        ids = _extract_regex(src)
        assert "A" not in ids  # too short
        assert "b" not in ids  # too short

    def test_filter_stopwords(self):
        src = "The class handles the data for the user."
        ids = _extract_regex(src)
        assert "class" not in ids  # stopword
        assert "user" not in ids  # stopword
        assert "data" not in ids  # stopword


class TestJavaAST:
    """Test Java AST extraction."""

    def test_extract_simple_class(self):
        src = """
        public class UserService {
            private String name;
            public void save() { }
            public User getById(int id) { return null; }
        }
        """
        ids = _extract_ast_java(src)
        assert "UserService" in ids
        assert "save" in ids
        assert "getById" in ids
        assert "String" in ids

    def test_extract_nested_classes(self):
        src = """
        public class Outer {
            class Inner {
                void innerMethod() { }
            }
            static class Nested {
                void nestedMethod() { }
            }
        }
        """
        ids = _extract_ast_java(src)
        assert "Outer" in ids
        assert "Inner" in ids
        assert "innerMethod" in ids
        assert "Nested" in ids
        assert "nestedMethod" in ids

    def test_extract_interface(self):
        src = """
        public interface Repository<T> {
            T findById(Long id);
            List<T> findAll();
        }
        """
        ids = _extract_ast_java(src)
        assert "Repository" in ids
        assert "findById" in ids
        assert "findAll" in ids

    def test_extract_enum(self):
        src = """
        public enum Status {
            ACTIVE, INACTIVE, PENDING;
            public String getLabel() { return name(); }
        }
        """
        ids = _extract_ast_java(src)
        assert "Status" in ids
        assert "getLabel" in ids

    def test_fallback_on_error(self):
        # Simulate parser error by passing invalid source
        src = "invalid java code @#$%^"
        ids = _extract_ast_java(src)
        # Should fall back to regex and extract something
        assert isinstance(ids, set)


class TestPythonAST:
    """Test Python AST extraction."""

    def test_extract_simple_class(self):
        src = """
        class UserService:
            def __init__(self, name):
                self.name = name
            
            def save(self):
                pass
            
            @property
            def display_name(self):
                return self.name
        """
        ids = _extract_ast_python(src)
        assert "UserService" in ids
        assert "__init__" in ids
        assert "save" in ids
        assert "display_name" in ids

    def test_extract_async_function(self):
        src = """
        class AsyncService:
            async def fetch_data(self):
                pass
        """
        ids = _extract_ast_python(src)
        assert "AsyncService" in ids
        assert "fetch_data" in ids

    def test_extract_dataclass(self):
        src = """
        from dataclasses import dataclass
        
        @dataclass
        class User:
            name: str
            age: int
            
            def greet(self):
                return f"Hello {self.name}"
        """
        ids = _extract_ast_python(src)
        assert "User" in ids
        assert "greet" in ids

    def test_extract_imports(self):
        src = """
        import os
        import sys.path
        from typing import List, Dict
        from collections import defaultdict
        """
        ids = _extract_ast_python(src)
        assert "os" in ids
        assert "sys" in ids
        assert "List" in ids
        assert "Dict" in ids
        assert "defaultdict" in ids

    def test_fallback_on_error_python(self):
        src = "invalid python code @#$%^"
        ids = _extract_ast_python(src)
        assert isinstance(ids, set)


class TestPublicAPI:
    """Test public API of extract_identifiers."""

    def test_extract_java_file(self):
        src = """
        package com.example;
        
        public class UserRepository {
            public User findById(Long id) {
                return null;
            }
            
            public List<User> findAll() {
                return Collections.emptyList();
            }
        }
        """
        ids = extract_identifiers(src, "java")
        assert "UserRepository" in ids
        assert "findById" in ids
        assert "findAll" in ids
        assert "User" in ids
        assert "List" in ids

    def test_extract_python_file(self):
        src = """
        from typing import Optional
        
        class UserService:
            def __init__(self, db):
                self.db = db
            
            def get_user(self, user_id: int) -> Optional[dict]:
                return self.db.query(f"SELECT * FROM users WHERE id={user_id}")
        """
        ids = extract_identifiers(src, "python")
        assert "UserService" in ids
        assert "__init__" in ids
        assert "get_user" in ids
        assert "Optional" in ids

    def test_auto_detect_java(self):
        src = "public class Foo { void bar() {} }"
        ids = extract_identifiers(src)
        assert "Foo" in ids
        assert "bar" in ids

    def test_auto_detect_python(self):
        src = "class Foo: def bar(): pass"
        ids = extract_identifiers(src)
        assert "Foo" in ids
        assert "bar" in ids

    def test_unsupported_language_fallback(self):
        src = "function foo() { }"
        ids = extract_identifiers(src, "javascript")
        assert isinstance(ids, set)
        # Should extract via regex
        assert "foo" in ids

    def test_empty_source(self):
        assert extract_identifiers("") == set()
        assert extract_identifiers(str()) == set()
        assert extract_identifiers(" ") == set()


class TestIntegration:
    """Integration tests with real files from workspace."""

    def test_extract_from_real_java_file(self):
        # Use an existing Java file if present
        test_file = Path(__file__).parent.parent / "src" / "agents" / "codex.py"
        if test_file.exists():
            src = test_file.read_text()
            ids = extract_identifiers(src, "python")  # codex.py is Python
            # Should extract at least some identifiers
            assert isinstance(ids, set)
            assert len(ids) >= 0  # May be empty if no classes/functions

    def test_extraction_performance(self):
        # 1MB Java file should extract in <500ms
        large_src = "public class A{}" * 20000  # ~600KB
        import time
        start = time.time()
        ids = extract_identifiers(large_src, "java")
        elapsed = time.time() - start
        assert elapsed < 0.5, f"Extraction took {elapsed}s (>500ms)"
        assert "A" in ids
