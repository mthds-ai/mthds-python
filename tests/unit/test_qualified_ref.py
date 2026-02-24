import pytest

from mthds.package.qualified_ref import QualifiedRef, QualifiedRefError


class TestQualifiedRef:
    """Tests for the mthds.package.qualified_ref module."""

    # --- parse ---

    def test_parse_empty_raises(self):
        with pytest.raises(QualifiedRefError, match="empty"):
            QualifiedRef.parse("")

    def test_parse_leading_dot_raises(self):
        with pytest.raises(QualifiedRefError, match="start or end"):
            QualifiedRef.parse(".foo")

    def test_parse_trailing_dot_raises(self):
        with pytest.raises(QualifiedRefError, match="start or end"):
            QualifiedRef.parse("foo.")

    def test_parse_consecutive_dots_raises(self):
        with pytest.raises(QualifiedRefError, match="consecutive dots"):
            QualifiedRef.parse("foo..bar")

    def test_parse_bare_ref(self):
        ref = QualifiedRef.parse("compute_score")
        assert ref.domain_path is None
        assert ref.local_code == "compute_score"

    def test_parse_single_dot(self):
        ref = QualifiedRef.parse("scoring.compute_score")
        assert ref.domain_path == "scoring"
        assert ref.local_code == "compute_score"

    def test_parse_multi_dot_splits_on_last(self):
        ref = QualifiedRef.parse("legal.contracts.extract_clause")
        assert ref.domain_path == "legal.contracts"
        assert ref.local_code == "extract_clause"

    # --- parse_concept_ref ---

    def test_parse_concept_ref_valid(self):
        ref = QualifiedRef.parse_concept_ref("legal.contracts.NonCompeteClause")
        assert ref.domain_path == "legal.contracts"
        assert ref.local_code == "NonCompeteClause"

    def test_parse_concept_ref_non_pascal_case_raises(self):
        with pytest.raises(QualifiedRefError, match="PascalCase"):
            QualifiedRef.parse_concept_ref("legal.contracts.not_pascal")

    def test_parse_concept_ref_non_snake_case_domain_raises(self):
        with pytest.raises(QualifiedRefError, match="snake_case"):
            QualifiedRef.parse_concept_ref("Legal.NonCompeteClause")

    # --- parse_pipe_ref ---

    def test_parse_pipe_ref_valid(self):
        ref = QualifiedRef.parse_pipe_ref("scoring.compute_score")
        assert ref.domain_path == "scoring"
        assert ref.local_code == "compute_score"

    def test_parse_pipe_ref_non_snake_case_local_raises(self):
        with pytest.raises(QualifiedRefError, match="snake_case"):
            QualifiedRef.parse_pipe_ref("scoring.ComputeScore")

    def test_parse_pipe_ref_non_snake_case_domain_raises(self):
        with pytest.raises(QualifiedRefError, match="snake_case"):
            QualifiedRef.parse_pipe_ref("Scoring.compute_score")

    # --- properties ---

    def test_is_qualified_true(self):
        ref = QualifiedRef.parse("domain.code")
        assert ref.is_qualified is True

    def test_is_qualified_false(self):
        ref = QualifiedRef.parse("code")
        assert ref.is_qualified is False

    def test_full_ref_qualified(self):
        ref = QualifiedRef.parse("domain.code")
        assert ref.full_ref == "domain.code"

    def test_full_ref_bare(self):
        ref = QualifiedRef.parse("code")
        assert ref.full_ref == "code"

    # --- locality ---

    def test_is_local_to_bare(self):
        """Bare refs are local to any domain."""
        ref = QualifiedRef.parse("compute_score")
        assert ref.is_local_to("scoring") is True

    def test_is_local_to_same_domain(self):
        ref = QualifiedRef.parse("scoring.compute_score")
        assert ref.is_local_to("scoring") is True

    def test_is_local_to_different_domain(self):
        ref = QualifiedRef.parse("scoring.compute_score")
        assert ref.is_local_to("legal") is False

    def test_is_external_to_bare(self):
        """Bare refs are never external."""
        ref = QualifiedRef.parse("compute_score")
        assert ref.is_external_to("scoring") is False

    def test_is_external_to_different_domain(self):
        ref = QualifiedRef.parse("scoring.compute_score")
        assert ref.is_external_to("legal") is True

    def test_is_external_to_same_domain(self):
        ref = QualifiedRef.parse("scoring.compute_score")
        assert ref.is_external_to("scoring") is False

    # --- cross-package ---

    def test_has_cross_package_prefix_true(self):
        assert QualifiedRef.has_cross_package_prefix("alias->domain.pipe") is True

    def test_has_cross_package_prefix_false(self):
        assert QualifiedRef.has_cross_package_prefix("domain.pipe") is False

    def test_split_cross_package_ref_valid(self):
        alias, remainder = QualifiedRef.split_cross_package_ref("my_dep->scoring.compute_score")
        assert alias == "my_dep"
        assert remainder == "scoring.compute_score"

    def test_split_cross_package_ref_no_arrow_raises(self):
        with pytest.raises(QualifiedRefError, match="not a cross-package"):
            QualifiedRef.split_cross_package_ref("no_arrow_here")

    def test_split_cross_package_ref_multiple_arrows(self):
        """Splits on first '->' only."""
        alias, remainder = QualifiedRef.split_cross_package_ref("a->b->c")
        assert alias == "a"
        assert remainder == "b->c"
