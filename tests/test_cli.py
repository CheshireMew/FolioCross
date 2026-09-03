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
    import json

    job_id = json.loads(imported.stdout)["job_id"]
    run = runner.invoke(app, ["--workspace", str(workspace), "run", job_id, "--json"])
    assert run.exit_code == 0, run.stdout
    assert json.loads(run.stdout)["status"] == "completed"
