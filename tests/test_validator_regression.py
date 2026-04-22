"""Test suite proving the validator no longer rejects the false positives from
the 2026-04-21 codex run.

Each test case mirrors a real failure observed in the user's logs.

Run with: pytest tests/test_validator_regression.py -v
"""

import pytest
from src.rag.validator import validate_doc, extract_candidates, _ENGLISH_STOPWORDS


# ============================================================
# Real failures from the logs — each MUST now pass cleanly.
# ============================================================

def test_jaxrs_annotations_not_flagged():
    """The Class abstain: every name was either an English word,
    a real JAX-RS annotation, or a real constant from the source."""
    source = """
    @ApplicationPath("/Content")
    public class Application extends javax.ws.rs.core.Application {
        @Path("/existFile")
        @Produces(MediaType.APPLICATION_OCTET_STREAM)
        public Response existFile(@QueryParam("sourceID") String iVariableName) {
            String CONTENT_PREFERENCES_PATH = getConfig();
            JSONObject contentPreferences = new JSONObject();
            return Response.ok().build();
        }
        @Path("/getDocumentationFile")
        public Response getDoc(@QueryParam("activityID") String activityID,
                               @QueryParam("activityName") String activityName) {
            return Response.ok().build();
        }
    }
    """
    doc = """
    The Application class is annotated with @ApplicationPath("/Content").
    It provides REST endpoints based on JAX-RS, including:
    - @Path("/existFile") which serves application/octet-stream and checks
      the existence of a file based on the sourceID variable.
    - @Path("/getDocumentationFile") which retrieves a file based on
      activityID and activityName parameters.

    The CONTENT_PREFERENCES_PATH constant holds the configuration path.
    The iVariableName parameter is mapped from sourceID.
    JSONObject is used for the contentPreferences setting.
    """
    issues = validate_doc(
        doc_text=doc,
        source_text=source,
        known_identifiers={"Application", "Response", "iVariableName",
                           "CONTENT_PREFERENCES_PATH", "contentPreferences",
                           "existFile", "getDoc", "activityID", "activityName"},
        noise_filter={"JAX-RS", "JAX", "REST", "JSONObject"},  # noise_filter is light intentionally
        language="java",
        file_path="Example/Application.java",
    )
    assert issues == [], f"unexpected issues: {issues}"


def test_english_prose_words_never_flagged():
    """Prose verbs and adjectives must never appear in issues."""
    source = "class Foo {}"
    doc = """
    The Foo class provides a representation of the entity. It contains methods
    based on the configuration. Provided that all dependencies are present,
    it serves the application correctly.
    """
    issues = validate_doc(
        doc_text=doc,
        source_text=source,
        known_identifiers={"Foo"},
        noise_filter=set(),
        language="java",
        file_path="x.java",
    )
    # Foo is in source, all other words are English prose.
    assert issues == [], f"unexpected issues: {issues}"


def test_doc_md_and_line_never_flagged():
    """Bug #5: prompt-template artifacts must be in the stoplist."""
    source = "class Bar {}"
    doc = "The Bar class is documented in doc_md format with line numbers."
    issues = validate_doc(
        doc_text=doc,
        source_text=source,
        known_identifiers={"Bar"},
        noise_filter=set(),
        language="java",
        file_path="x.java",
    )
    assert issues == [], f"unexpected issues: {issues}"


def test_xml_files_bypass_validation():
    """Bug #6: XML / properties / YAML / CSV files are not validated."""
    source = """<?xml version='1.0'?>
    <web-app>
        <filter>
            <init-param>
                <param-name>casServerLoginUrl</param-name>
                <param-value>${PASSPORT}/login</param-value>
            </init-param>
        </filter>
    </web-app>"""
    doc = """
    The web.xml configures CAS authentication. It defines several filters
    including casServerLoginUrl mapped to ${PASSPORT}/login.
    The skipFilterUrlPatterns and refreshPeriod settings are also defined.
    """
    issues = validate_doc(
        doc_text=doc,
        source_text=source,
        known_identifiers=set(),  # XML extractor doesn't return much
        noise_filter=set(),
        language="xml",
        file_path="WEB-INF/web.xml",
    )
    # Bypassed entirely.
    assert issues == [], f"validator should bypass non-source files: {issues}"


def test_real_hallucination_still_caught():
    """Sanity: the validator still catches actual hallucinations."""
    source = "class Foo { void bar() {} }"
    doc = "The Foo class calls AuthenticationService.validateToken() and JwtParser.parse()."
    issues = validate_doc(
        doc_text=doc,
        source_text=source,
        known_identifiers={"Foo", "bar"},
        noise_filter=set(),
        language="java",
        file_path="x.java",
    )
    names = {i["name"] for i in issues}
    assert "AuthenticationService" in names or "JwtParser" in names, (
        f"validator failed to catch hallucinations: {issues}"
    )


def test_camelcase_single_hump_not_candidate():
    """Bug #1: single-hump words like 'Application' are not candidates by themselves
    (they live in the noise filter for safety, not in the candidate set)."""
    candidates = extract_candidates("The Application uses Service patterns.")
    names = {c[0] for c in candidates}
    # Application has only one hump → not a CamelCase candidate.
    # AuthenticationService would be (Auth + entication + Service is 2+ humps).
    assert "Application" not in names, (
        "single-hump words should not be candidates"
    )


def test_snake_case_requires_underscore():
    """Bug #1: 'application' alone is not a snake_case candidate."""
    candidates = extract_candidates("the application provides endpoints")
    names = {c[0] for c in candidates}
    assert "application" not in names
    assert "endpoints" not in names


def test_snake_case_with_underscore_is_candidate():
    candidates = extract_candidates("calls auth_service.validate_token()")
    names = {c[0] for c in candidates}
    assert "auth_service" in names
    assert "validate_token" in names


def test_constants_are_candidates():
    candidates = extract_candidates("uses CONTENT_PREFERENCES_PATH and API_KEY")
    names = {c[0] for c in candidates}
    assert "CONTENT_PREFERENCES_PATH" in names
    assert "API_KEY" in names


def test_dotted_paths_are_candidates():
    candidates = extract_candidates("imports com.example.Foo and javax.ws.rs.Path")
    names = {c[0] for c in candidates}
    assert "com.example.Foo" in names
    assert "javax.ws.rs.Path" in names


def test_backtick_normalization():
    """Backticked tokens get cleaned of @, parens, quotes."""
    candidates = extract_candidates(
        'uses `@Path("/foo")` annotation and `Response.ok()`'
    )
    names = {c[0] for c in candidates}
    assert "Path" in names
    # Response.ok() -> Response extracted by _normalize_backticked
    assert "Response" in names or "Response.ok" in names


def test_stopwords_present():
    """Sanity check the stoplist covers the verbs that broke previous runs."""
    for word in ["annotated", "provided", "containing", "representing",
                 "following", "including", "based", "mapped"]:
        assert word in _ENGLISH_STOPWORDS, f"missing stopword: {word}"
