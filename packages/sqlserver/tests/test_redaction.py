"""Unit tests for PII redaction."""

from __future__ import annotations

import pandas as pd
import pytest

from sqlserver.redaction import is_pii_column, mask_dataframe


class TestIsPiiColumn:
    @pytest.mark.parametrize(
        "name",
        [
            "Email",
            "EmailAddress",
            "UserEmail",
            "PhoneNumber",
            "PrimaryPhone",
            "CreditCard",
            "CreditCardNumber",
            "Password",
            "PasswordHash",
            "PasswordSalt",
            "SSN",
            "SocialSecurityNumber",
        ],
    )
    def test_flags_pii_names(self, name: str) -> None:
        assert is_pii_column(name) is True

    @pytest.mark.parametrize(
        "name",
        ["FirstName", "LastName", "CustomerID", "OrderDate", "Quantity", "Status", "rowguid"],
    )
    def test_does_not_flag_non_pii(self, name: str) -> None:
        assert is_pii_column(name) is False


class TestMaskDataframe:
    def test_mask_replaces_email_values_deterministically(self) -> None:
        df = pd.DataFrame(
            {"EmailAddress": ["a@x.com", "b@y.com", "a@x.com", None], "Id": [1, 2, 3, 4]}
        )
        masked = mask_dataframe(df, ["EmailAddress"])

        # Non-PII columns untouched
        assert list(masked["Id"]) == [1, 2, 3, 4]

        # PII column: every non-null value becomes REDACTED_<8 hex>
        for v in masked["EmailAddress"].dropna():
            assert (
                isinstance(v, str) and v.startswith("REDACTED_") and len(v) == len("REDACTED_") + 8
            )

        # Same input => same hash (deterministic)
        assert masked["EmailAddress"][0] == masked["EmailAddress"][2]
        # Different input => different hash
        assert masked["EmailAddress"][0] != masked["EmailAddress"][1]

        # None stays None
        assert pd.isna(masked["EmailAddress"][3])

    def test_mask_ignores_unknown_columns(self) -> None:
        df = pd.DataFrame({"a": [1, 2]})
        # Should not raise — columns not in df are skipped
        assert_frame_unchanged(df, mask_dataframe(df, ["DoesNotExist"]))

    def test_mask_returns_copy_not_view(self) -> None:
        df = pd.DataFrame({"Email": ["x@y.com"]})
        masked = mask_dataframe(df, ["Email"])
        # Original unchanged
        assert df["Email"][0] == "x@y.com"
        assert masked["Email"][0].startswith("REDACTED_")


def assert_frame_unchanged(a: pd.DataFrame, b: pd.DataFrame) -> None:
    assert a.columns.tolist() == b.columns.tolist()
    assert a.values.tolist() == b.values.tolist()
