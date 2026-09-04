import json
from pathlib import Path

from typer.testing import CliRunner

from foliocross.cli import app


def test_doctor_and_fake_end_to_end_cli(tmp_path: Path):
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    doctor = runner.invoke(app, ["--workspace", str(workspace), "doctor", "--json"])
    assert doctor.exit_code == 0
    assert '"workspace"' in doctor.stdout
    source = tmp_path / "cli.txt"
    source.write_text("A command line paragraph.", encoding="utf-8")
    imported = runner.invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "import",
            str(source),
            "--fake",
            "--output-format",
            "txt",
            "--json",
        ],
    )
    assert imported.exit_code == 0, imported.stdout
    job_id = json.loads(imported.stdout)["job_id"]
    run = runner.invoke(app, ["--workspace", str(workspace), "run", job_id, "--json"])
    assert run.exit_code == 0, run.stdout
    assert json.loads(run.stdout)["status"] == "completed"

    glossary_path = tmp_path / "terms.json"
    glossary_path.write_text(
        json.dumps([{"source": "command", "target": "命令"}], ensure_ascii=False),
        encoding="utf-8",
    )
    glossary_import = runner.invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "glossary",
            "import",
            job_id,
            str(glossary_path),
            "--json",
        ],
    )
    assert glossary_import.exit_code == 0, glossary_import.stdout
    assert json.loads(glossary_import.stdout)["terms"] == 1
    exported_path = tmp_path / "exported-terms.json"
    glossary_export = runner.invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "glossary",
            "export",
            job_id,
            "--output",
            str(exported_path),
            "--json",
        ],
    )
    assert glossary_export.exit_code == 0, glossary_export.stdout
    assert json.loads(glossary_export.stdout)["path"] == str(exported_path.resolve())


def test_cli_provider_override_clears_deepseek_pricing(tmp_path: Path):
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    source = tmp_path / "provider.txt"
    source.write_text("Provider-specific pricing.", encoding="utf-8")
    imported = runner.invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "import",
            str(source),
            "--provider",
            "openai",
            "--base-url",
            "https://api.openai.com/v1",
            "--model",
            "gpt-test",
            "--json",
        ],
    )
    assert imported.exit_code == 0, imported.stdout
    job_id = json.loads(imported.stdout)["job_id"]
    status = runner.invoke(
        app,
        ["--workspace", str(workspace), "jobs", "status", job_id, "--json"],
    )
    job = json.loads(status.stdout)["job"]
    profile = job["config"]["profile"]
    assert profile["provider"] == "openai"
    assert profile["input_price_per_million"] is None
    assert profile["cached_input_price_per_million"] is None
    assert profile["output_price_per_million"] is None
    assert job["cost_configured"] is False


def test_cli_rejects_invalid_output_before_creating_a_job(tmp_path: Path):
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    source = tmp_path / "invalid-output.txt"
    source.write_text("Do not create a job.", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "import",
            str(source),
            "--output-format",
            "pdf",
            "--json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "unsupported_output"
