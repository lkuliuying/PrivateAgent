"""发布工作流的离线边界测试；直接用 unittest 运行，不加载项目 conftest。"""

import json
import os
import shutil
import stat
import subprocess
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "verify-release.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "signpath-release.yml"
PWSH = shutil.which("pwsh")
GIT = shutil.which("git")


@unittest.skipUnless(PWSH and GIT, "需要本地 PowerShell 7 和 Git")
class ReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.test_root = (ROOT / ".tmp/release-workflow-tests").resolve()
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.repo = self.test_root / uuid.uuid4().hex
        # Windows 受限环境中避免 tempfile 的 0700 ACL 阻止当前测试子进程访问。
        self.repo.mkdir()
        self.addCleanup(self.cleanup_repo)
        allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"}
        self.env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        self.env.update(
            USERPROFILE=str(self.repo),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=str(self.repo / "empty-gitconfig"),
            GIT_TERMINAL_PROMPT="0",
            RELEASE_TAG="v1.0.0",
            RELEASE_EVENT_NAME="workflow_dispatch",
            RELEASE_EVENT_SHA="not-the-selected-tag",
            GITHUB_OUTPUT=str(self.repo / "github-output"),
            GITHUB_REPOSITORY="fixture/repository",
        )
        config = self.repo / "apps/desktop/src-tauri/tauri.conf.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")
        (self.repo / "scripts").mkdir()
        shutil.copyfile(GUARD, self.repo / "scripts/verify-release.ps1")
        self.git("init", "--quiet")
        self.git("config", "user.email", "release-test@example.invalid")
        self.git("config", "user.name", "Release Test")
        self.git("add", "apps")
        self.git("commit", "--quiet", "-m", "fixture")
        self.commit = self.git("rev-parse", "HEAD")
        self.git("tag", "v1.0.0")

    def cleanup_repo(self):
        target = self.repo.resolve()
        if target.parent != self.test_root or not target.is_relative_to(self.test_root):
            raise RuntimeError("测试清理路径不在专用目录中")
        # Git 对象在 Windows 上可能只读；仅恢复本用例目录内的写权限。
        def retry_readonly(function, path, error):
            candidate = Path(path).resolve()
            if not candidate.is_relative_to(target):
                raise RuntimeError("测试清理项越过用例目录") from error
            os.chmod(candidate, candidate.stat().st_mode | stat.S_IWRITE)
            function(path)

        shutil.rmtree(target, onexc=retry_readonly)

    def git(self, *args):
        return subprocess.run(
            [GIT, *args], cwd=self.repo, env=self.env, check=True,
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        ).stdout.strip()

    def run_ps(self, script, **overrides):
        path = self.repo / "test-launcher.ps1"
        path.write_text("$ErrorActionPreference = 'Stop'\n" + script, encoding="utf-8")
        return subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(path)],
            cwd=self.repo, env={**self.env, **overrides}, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=30,
        )

    def source(self, **overrides):
        return self.run_ps("./scripts/verify-release.ps1 -Mode Source\n", **overrides)

    def assert_failed(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stdout + result.stderr)

    def test_lightweight_tag_uses_its_commit_in_manual_evidence(self):
        result = self.source()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.repo / "github-output").read_text(encoding="utf-8").splitlines(),
            ["tag=v1.0.0", "version=1.0.0", f"commit={self.commit}"],
        )

    def test_annotated_tag_is_peeled_and_release_event_is_verified(self):
        self.git("tag", "-d", "v1.0.0")
        self.git("tag", "-a", "v1.0.0", "-m", "annotated fixture")
        self.assertNotEqual(self.git("rev-parse", "v1.0.0"), self.commit)
        result = self.source(RELEASE_EVENT_NAME="release", RELEASE_EVENT_SHA=self.commit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"commit={self.commit}", (self.repo / "github-output").read_text())

    def test_different_checked_out_commit_is_rejected(self):
        self.git("commit", "--allow-empty", "--quiet", "-m", "later commit")
        self.assert_failed(self.source(), "does not match the release tag commit")
        self.assertFalse((self.repo / "github-output").exists())

    def test_missing_tag_does_not_fall_back_to_same_named_branch(self):
        self.git("tag", "-d", "v1.0.0")
        self.git("branch", "v1.0.0")
        self.assert_failed(self.source(), "release verification stopped")

    def test_wrong_or_missing_event_sha_is_rejected(self):
        for value in ("0" * 40, ""):
            with self.subTest(value=value):
                self.assert_failed(
                    self.source(RELEASE_EVENT_NAME="release", RELEASE_EVENT_SHA=value),
                    "does not match the release event commit",
                )

    def test_wrong_version_and_remote_channel_are_rejected(self):
        for tag in ("v2.0.0", "remote-v1.0.0"):
            with self.subTest(tag=tag):
                self.git("tag", tag)
                self.assert_failed(self.source(RELEASE_TAG=tag), "does not match the application version")

    def test_tag_input_is_data_and_cannot_inject_powershell(self):
        result = self.source(RELEASE_TAG="v1.0.0';New-Item INJECTED;#")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / "INJECTED").exists())
        self.assert_failed(self.source(RELEASE_TAG="v1.0.0\ncommit=forged"), "one existing tag name")

    def test_missing_output_or_unknown_event_is_rejected(self):
        self.assert_failed(self.source(GITHUB_OUTPUT=""), "GITHUB_OUTPUT is required")
        self.assert_failed(self.source(RELEASE_EVENT_NAME="push"), "Unsupported release event")

    def prepare_upload(self, response=None, *, raw_response=None):
        # gh 替身只读取本地夹具并记录调用，任何命令都不会访问网络。
        fake_bin = self.repo / "fake-bin"
        fake_bin.mkdir()
        (fake_bin / "gh.ps1").write_text(
            "param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)\n"
            "$Arguments | ConvertTo-Json -Compress | Add-Content -LiteralPath $env:GH_CALLS\n"
            "if ($Arguments[0] -eq 'release' -and $Arguments[1] -eq 'view') {\n"
            "  Get-Content -LiteralPath $env:GH_RESPONSE -Raw\n"
            "  exit ([int]$env:GH_VIEW_EXIT)\n"
            "}\n"
            "if ($Arguments[0] -eq 'release' -and $Arguments[1] -eq 'upload') {\n"
            "  exit ([int]$env:GH_UPLOAD_EXIT)\n"
            "}\n"
            "throw 'Unexpected offline gh invocation.'\n",
            encoding="utf-8",
        )
        response_path = self.repo / "release-response.json"
        if raw_response is None:
            response = {"tagName": "v1.0.0", "assets": []} if response is None else response
            raw_response = json.dumps(response)
        response_path.write_text(raw_response, encoding="utf-8")
        installer = self.repo / "artifacts" / "PrivateAgent 1.0.0-setup.exe"
        paths = [installer, Path(str(installer) + ".sig"), self.repo / "dist/latest.json"]
        paths += [self.repo / "dist" / f"{name}-1.0.0.{suffix}" for name, suffix in (
            ("codesign-status", "json"), ("signpath-request", "json"), ("release-manifest", "md"),
        )]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture artifact", encoding="utf-8")
        self.env.update(
            PATH=str(fake_bin) + os.pathsep + self.env["PATH"],
            GH_RESPONSE=str(response_path),
            GH_CALLS=str(self.repo / "gh-calls.jsonl"),
            GH_VIEW_EXIT="0",
            GH_UPLOAD_EXIT="0",
            SIGNED_INSTALLER_PATH=str(installer),
            RELEASE_VERSION="1.0.0",
        )
        return paths

    def upload_block(self):
        # 执行工作流自身的上传块，验证预检失败确实阻止后续上传。
        content = WORKFLOW.read_text(encoding="utf-8")
        section = content.split("      - name: Attach verified assets to GitHub Release\n", 1)[1]
        block = section.split("        run: |\n", 1)[1]
        return "\n".join(line[10:] for line in block.splitlines() if line.startswith("          "))

    def gh_calls(self):
        path = self.repo / "gh-calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_all_new_assets_upload_without_overwrite_option(self):
        paths = self.prepare_upload()
        result = self.run_ps(self.upload_block())
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.gh_calls()
        self.assertEqual([call[:2] for call in calls], [["release", "view"], ["release", "upload"]])
        self.assertNotIn("--clobber", calls[1])
        self.assertEqual(calls[1][2], "v1.0.0")
        self.assertIn(str(paths[0]), calls[1])
        self.assertEqual(len(calls[1][3:-2]), 6)

    def test_existing_asset_prevents_entire_upload(self):
        self.prepare_upload({"tagName": "v1.0.0", "assets": [{"name": "latest.json"}]})
        result = self.run_ps(self.upload_block())
        self.assert_failed(result, "refusing to overwrite")
        self.assertEqual([call[:2] for call in self.gh_calls()], [["release", "view"]])

    def test_metadata_failure_stops_upload_even_if_json_was_returned(self):
        self.prepare_upload()
        self.assert_failed(self.run_ps(self.upload_block(), GH_VIEW_EXIT="7"), "exit code 7")
        self.assertEqual(len(self.gh_calls()), 1)

    def test_malformed_incomplete_or_wrong_release_response_stops_upload(self):
        self.prepare_upload()
        for value in ("not json", "null", "{}", '{"tagName":"v1.0.0","assets":null}',
                      '{"tagName":"v2.0.0","assets":[]}',
                      '{"tagName":"v1.0.0","assets":[{}]}'):
            with self.subTest(value=value):
                Path(self.env["GH_RESPONSE"]).write_text(value, encoding="utf-8")
                result = self.run_ps(self.upload_block())
                self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(call[:2] == ["release", "view"] for call in self.gh_calls()))

    def test_missing_or_empty_local_asset_stops_before_remote_request(self):
        paths = self.prepare_upload()
        paths[0].write_bytes(b"")
        self.assert_failed(self.run_ps(self.upload_block()), "non-empty regular file")
        paths[0].unlink()
        self.assertNotEqual(self.run_ps(self.upload_block()).returncode, 0)
        self.assertEqual(self.gh_calls(), [])

    def test_duplicate_local_names_are_rejected(self):
        paths = self.prepare_upload()
        script = "./scripts/verify-release.ps1 -Mode Assets -AssetPaths @($env:SIGNED_INSTALLER_PATH, $env:SIGNED_INSTALLER_PATH)"
        self.assertTrue(paths[0].exists())
        self.assert_failed(self.run_ps(script), "Duplicate local release asset name")
        self.assertEqual(self.gh_calls(), [])

    def test_racing_or_failed_upload_is_reported_and_not_retried(self):
        self.prepare_upload()
        self.assert_failed(self.run_ps(self.upload_block(), GH_UPLOAD_EXIT="9"), "inspect partial assets before retrying")
        self.assertEqual(len(self.gh_calls()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
