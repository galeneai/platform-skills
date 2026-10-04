"""Execute the documented formatters and inspect emitted lines, not their wording."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "references" / "logging.md"
CUSTOMER = "BoardMinutes-acquisition-amount-83291"
SECRET = "provider-secret-734891"


def example(section, language):
    content = REFERENCE.read_text().split(f"## {section}\n", 1)[1]
    return re.search(rf"```{language}\n(.*?)\n```", content, re.S).group(1)


def emitted(command, program):
    result = subprocess.run(command, input=program, text=True, capture_output=True, check=True)
    assert CUSTOMER not in result.stdout + result.stderr
    assert SECRET not in result.stdout + result.stderr
    lines = [json.loads(line) for line in (result.stdout + result.stderr).splitlines()]
    assert len(lines) == 1
    line = lines[0]
    assert line["level"] == "ERROR" and line["timestamp"].endswith("Z")
    return line


def test_python_example_omits_library_exception_content_and_keeps_handling_source():
    program = example("Python", "python") + f'''
configure_logging()
try:
    raise RuntimeError("{CUSTOMER} https://provider.test?token={SECRET}")
except RuntimeError:
    logging.getLogger("fixture.api").exception("export_failed", extra={{"impact": "failed"}})
'''
    line = emitted([sys.executable, "-"], program)
    assert line["error_type"] == "RuntimeError" and line["impact"] == "failed"
    assert line["filename"] and line["line_number"]


def test_node_preload_example_does_not_render_library_error_message_or_stack():
    node = shutil.which("node")
    assert node, "Run the example verification on the native host with Node in PATH"
    program = example("Node console preload", "js") + f'''
console.error(new Error("{CUSTOMER} https://provider.test?token={SECRET}"), "export_failed");
'''
    line = emitted([node, "--input-type=module"], program)
    assert line["error_types"] == ["Error"] and "export_failed" in line["message"]
