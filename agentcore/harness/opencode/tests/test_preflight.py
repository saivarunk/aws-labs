import unittest

from scripts import preflight


class PreflightTests(unittest.TestCase):
    def test_non_on_demand_model_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "on-demand"):
            preflight.check_model(
                {"inferenceTypesSupported": ["PROVISIONED"], "modelArn": "model"}
            )

    def test_missing_model_arn_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "ARN is missing"):
            preflight.check_model({"inferenceTypesSupported": ["ON_DEMAND"]})

    def test_foundation_model_arn_preserved(self):
        arn = "arn:aws:bedrock:us-east-1::foundation-model/example"
        self.assertEqual(
            preflight.check_model(
                {"inferenceTypesSupported": ["ON_DEMAND"], "modelArn": arn}
            ),
            [arn],
        )

    def test_unsupported_region_is_blocked_before_aws_call(self):
        with self.assertRaisesRegex(RuntimeError, "not been verified"):
            preflight.run("unverified-region", "example", None)

    def test_sensitive_shapes_redacted(self):
        values = [
            "123456789012",
            "ASIA" + "A" * 16,
            "eyJhbGciOiJIUzI1NiJ9.payload.signature",
            "ghp_" + "a" * 36,
        ]
        result = preflight.redact(" ".join(values))
        for value in values:
            self.assertNotIn(value, result)


if __name__ == "__main__":
    unittest.main()
