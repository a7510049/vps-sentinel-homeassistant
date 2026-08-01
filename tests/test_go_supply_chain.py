from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[1]
WORKFLOW = (
    ROOT / ".github" / "workflows" / "validate.yml"
).read_text(encoding="utf-8")
ADR = (
    ROOT / "docs" / "adr" / "0002-go-agent-evaluation.md"
).read_text(encoding="utf-8")
GO_MOD = (ROOT / "go-agent" / "go.mod").read_text(encoding="utf-8")


class GoSupplyChainTests(unittest.TestCase):
    def test_go_toolchain_uses_the_scanned_security_floor(self):
        self.assertIn("go 1.25.12", GO_MOD)
        self.assertIn("最低為 1.25.12", ADR)
        self.assertNotIn("go 1.24.0", GO_MOD)

    def test_vulnerability_scanner_is_version_pinned(self):
        self.assertIn(
            "golang.org/x/vuln/cmd/govulncheck@v1.6.0",
            WORKFLOW,
        )
        self.assertIn("govulncheck ./...", WORKFLOW)
        self.assertIn(
            "govulncheck -mode binary go-agent-amd64",
            WORKFLOW,
        )
        self.assertIn(
            "govulncheck -mode binary go-agent-arm64",
            WORKFLOW,
        )

    def test_sbom_action_and_syft_are_pinned(self):
        action = re.findall(
            r"anchore/sbom-action@([0-9a-f]{40})",
            WORKFLOW,
        )
        self.assertEqual(
            action,
            ["4a30bbadbe35d73a1729ee95a9196544192d905e"] * 2,
        )
        self.assertEqual(WORKFLOW.count("syft-version: v1.44.0"), 2)
        self.assertIn("go-agent-amd64.spdx.json", WORKFLOW)
        self.assertIn("go-agent-arm64.spdx.json", WORKFLOW)
        self.assertEqual(WORKFLOW.count('SPDX-2.3'), 2)

    def test_adr_does_not_treat_supply_chain_as_optional(self):
        self.assertIn("checksum、SBOM 及依賴漏洞掃描", ADR)
        self.assertIn("不得把 Go 設為預設", ADR)


if __name__ == "__main__":
    unittest.main()
