from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[1]
        / "vendor/webnovel-writer/webnovel-writer/scripts"
    ),
)

import supervisor
import launcher
import context_pack
from chapter_commit import _validate_chapter_length


class ConfigTests(unittest.TestCase):
    def test_defaults_are_safe(self) -> None:
        config = supervisor.Config.load(Path("/definitely/missing/config.json"))
        self.assertEqual(config.batch_size, 5)
        self.assertEqual(config.max_revisions_per_chapter, 1)
        self.assertEqual(config.sandbox, "workspace-write")

    def test_rejects_dangerous_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"sandbox": "danger-full-access"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                supervisor.Config.load(path)

    def test_prompt_enforces_commit_gate(self) -> None:
        prompt = supervisor.prompt_for(12, supervisor.Config())
        self.assertIn("第 12 章", prompt)
        self.assertIn("不得使用子代理", prompt)
        self.assertIn(".codex/skills/novel-director/SKILL.md", prompt)
        self.assertIn("chapter-commit", prompt)

    def test_launcher_has_external_backup_directory(self) -> None:
        self.assertNotEqual(launcher.BACKUP_ROOT, launcher.ROOT)
        self.assertEqual(launcher.BACKUP_ROOT.name, "NovelCodexBackups")

    def test_codex_command_uses_supported_service_tier(self) -> None:
        command = supervisor.codex_command(
            supervisor.Config(), Path("/tmp/chapter-result.json")
        )
        self.assertIn('service_tier="fast"', command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("gpt-5.5", command)

    def test_context_packet_is_bounded_and_chapter_local(self) -> None:
        path = context_pack.build_packet(1)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["chapter"], 1)
        self.assertEqual(payload["title"], "妹妹死后三年，我接到了她的求救电话")
        self.assertLess(len(path.read_text(encoding="utf-8")), 30000)
        self.assertIn("must_cover_nodes", payload["directive"])
        self.assertEqual(payload["quality"]["target_chinese_chars"], [2000, 3000])

    def test_committed_chapter_length_is_within_hard_limit(self) -> None:
        count = _validate_chapter_length(context_pack.BOOK, 1)
        self.assertGreaterEqual(count, 2000)
        self.assertLessEqual(count, 3000)


if __name__ == "__main__":
    unittest.main()
