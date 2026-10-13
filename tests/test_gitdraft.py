"""실제 임시 Git 저장소 + 모의 REST 응답으로 외부 비용 없이 검증."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import urllib.error

from gitdraft.ai import generate
from gitdraft.cli import main, normalize, parser, redact_result
from gitdraft.git_context import collect, mask, DraftError

DRAFT = {"summary": "입력 검증을 개선했습니다.", "title": "fix: 입력 검증 개선",
         "what": ["app.py의 빈 입력 처리를 추가했습니다."],
         "why": ["잘못된 입력을 처리하기 위해 변경했습니다."],
         "how_to_test": ["권장 절차 (미실행): 빈 입력을 전달해 오류 메시지를 확인하세요."]}


def response(content=None, finish="stop"):
    result = MagicMock()
    result.__enter__.return_value.read.return_value = json.dumps({
        "choices": [{"finish_reason": finish, "message": {
            "content": json.dumps(DRAFT) if content is None else content}}]}).encode()
    return result


class RepoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = Path.cwd()
        os.chdir(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        Path("app.py").write_text("value = 1\n")
        self.git("add", "app.py")
        self.git("commit", "-qm", "initial")

    def tearDown(self):
        os.chdir(self.previous)
        self.temp.cleanup()

    def git(self, *args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    def run_cli(self, args, key=True):
        out, err = io.StringIO(), io.StringIO()
        env = {"AI_API_KEY": "test-key"} if key else {}
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def change(self):
        Path("app.py").write_text("value = 2\n")

    def test_clean_repo_no_api_or_key_needed(self):
        with patch("gitdraft.ai.urllib.request.build_opener") as opener:
            code, out, _ = self.run_cli(["commit"], key=False)
        self.assertEqual(code, 0)
        self.assertIn("변경 사항이 없습니다", out)
        self.assertIn("호출 횟수: 0", out)
        opener.assert_not_called()

    def test_staged_and_unstaged(self):
        self.change()
        self.git("add", "app.py")
        Path("app.py").write_text("value = 3\n")
        data = collect(True, 10, 200)
        self.assertIn("[STAGED]", data["diff"])
        self.assertIn("[UNSTAGED]", data["diff"])
        self.assertIn("+value = 2", data["diff"])
        self.assertIn("+value = 3", data["diff"])

    def test_initial_repository(self):
        with tempfile.TemporaryDirectory() as repo:
            os.chdir(repo)
            self.git("init", "-q")
            Path("new.py").write_text("pass\n")
            self.git("add", "new.py")
            self.assertIn("+pass", collect(True, 10, 200)["diff"])

    def test_untracked_only(self):
        Path("new.py").write_text("private content")
        data = collect(True, 10, 200)
        self.assertEqual(data["untracked_files"], 1)
        self.assertNotIn("private content", str(data))

    def test_rename_spaces_and_literal_pathspec(self):
        self.git("mv", "app.py", "new file[1].py")
        data = collect(True, 10, 200)
        self.assertEqual(data["files"][0]["old_path"], "app.py")
        self.assertIn("rename to new file[1].py", data["diff"])

    def test_deleted_file(self):
        Path("app.py").unlink()
        self.assertIn("-value = 1", collect(True, 10, 200)["diff"])

    def test_sensitive_files_excluded_and_values_masked(self):
        Path(".env").write_text("TOP_SECRET=should-not-send\n")
        self.git("add", ".env")
        Path("app.py").write_text('api_key = "sk-abcdefgh1234567890"\nemail = "hello@example.com"\n')
        data = collect(True, 10, 200)
        self.assertEqual(data["excluded_files"], 1)
        for secret in ("should-not-send", "sk-abcdefgh1234567890", "hello@example.com"):
            self.assertNotIn(secret, str(data))

    def test_all_sensitive_files_no_api(self):
        Path(".env").write_text("secret")
        with self.assertRaises(DraftError):
            collect(True, 10, 200)

    def test_limit_and_unsafe_mode(self):
        self.change()
        Path("other.py").write_text("pass")
        data = collect(False, 1, 2)
        self.assertEqual(len(data["files"]), 1)
        self.assertEqual(data["omitted_files"], 1)
        self.assertTrue(data["truncated"])
        self.assertLessEqual(len(data["diff"].splitlines()), 2)

    def test_missing_key(self):
        self.change()
        code, out, err = self.run_cli(["commit"], key=False)
        self.assertEqual(code, 1)
        self.assertIn("AI_API_KEY", err)
        self.assertIn("호출 횟수: 0", out)

    def test_preview(self):
        self.change()
        with patch("gitdraft.ai.urllib.request.build_opener") as opener:
            code, out, _ = self.run_cli(["all", "--preview"], key=False)
        self.assertEqual(code, 0)
        self.assertIn("+value = 2", out)
        opener.assert_not_called()

    def test_complete_flow_single_rest_call(self):
        self.change()
        with patch("gitdraft.ai.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = response()
            code, out, err = self.run_cli(["all", "-model", "gpt-4o-mini",
                                           "-temperature", "0.3", "-max-tokens", "900",
                                           "--context", "빈 입력 처리 개선"])
            opener.return_value.open.assert_called_once()
            request = opener.return_value.open.call_args.args[0]
        self.assertEqual((code, err), (0, ""))
        payload = json.loads(request.data)
        self.assertEqual(payload["max_completion_tokens"], 900)
        self.assertEqual(payload["temperature"], 0.3)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertIn("+value = 2", payload["messages"][1]["content"])
        self.assertIn("빈 입력 처리 개선", payload["messages"][1]["content"])
        for text in ("Commit Message", "PR Title", "## Why\n- ", "## What\n- ", "## How to Test\n- ", "호출 횟수: 1"):
            self.assertIn(text, out)

    def test_wrong_directory(self):
        Path("sub").mkdir()
        os.chdir("sub")
        with self.assertRaisesRegex(DraftError, "루트"):
            collect(True, 10, 200)


class OutputAndAPITests(unittest.TestCase):
    def test_title_limits_and_missing_sections(self):
        data, notices = normalize({"title": "feat: " + "가" * 100 + "\nextra", "summary": "변경"},
                                  {"truncated": False, "omitted_files": 0, "files": [{"path": "app.py"}]})
        self.assertLessEqual(len(data["commit_title"]), 72)
        self.assertLessEqual(len(data["title"]), 80)
        for key in ("why", "what", "how_to_test"):
            self.assertTrue(data[key])
        self.assertTrue(notices)

    def test_empty_title_rejected(self):
        with self.assertRaises(DraftError):
            normalize({"summary": "x", "title": "\n"}, {})

    def test_terminal_escape_removed(self):
        data, _ = normalize({**DRAFT, "title": "fix: \x1b[31m테스트\n두 줄"},
                            {"truncated": False, "omitted_files": 0})
        self.assertNotIn("\x1b", data["title"])
        self.assertNotIn("\n", data["title"])

    def test_recursive_mask_preserves_json(self):
        result = redact_result({"what": ['password = "secret"', "test-key"], "title": "fix: 수정"}, "test-key")
        self.assertEqual(result["title"], "fix: 수정")
        self.assertNotIn("secret", str(result))
        self.assertNotIn("test-key", str(result))

    def test_mask_multiline_private_key(self):
        self.assertNotIn("abcdef", mask("-----BEGIN RSA PRIVATE KEY-----\nabcdef\n-----END RSA PRIVATE KEY-----"))

    def test_invalid_options(self):
        for args in (["commit", "--temperature", "nan"], ["pr", "--max-tokens", "0"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser().parse_args(args)

    def test_api_failures_no_retry(self):
        for error in (urllib.error.HTTPError("url", 401, "key reflected", {}, None),
                      urllib.error.HTTPError("url", 429, "quota", {}, None),
                      urllib.error.URLError("DNS failure"), TimeoutError("timed out")):
            with self.subTest(error=error), patch("gitdraft.ai.urllib.request.build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(DraftError):
                    generate({}, "commit", "", "test-key", "model", 0.2, 1200)
                opener.return_value.open.assert_called_once()

    def test_invalid_or_incomplete_api_response(self):
        for content, finish in (("invalid json", "stop"), ("[]", "stop"), ("{}", "length")):
            with patch("gitdraft.ai.urllib.request.build_opener") as opener:
                opener.return_value.open.return_value = response(content, finish)
                with self.assertRaises(DraftError):
                    generate({}, "pr", "", "test-key", "model", 0.2, 1200)


if __name__ == "__main__":
    unittest.main()
