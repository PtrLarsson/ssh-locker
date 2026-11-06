import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "formula_pins.py"
spec = importlib.util.spec_from_file_location("formula_pins", SCRIPT)
formula_pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(formula_pins)

FORMULA = '''
class SshLocker < Formula
  url "https://github.com/PtrLarsson/ssh-locker/archive/refs/tags/v0.1.0.tar.gz"

  resource "pyobjc-core" do
    url "https://files.pythonhosted.org/packages/83/58/7bab/pyobjc_core-13.0.tar.gz"
    sha256 "ffe1"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/f6/cc/6253/typing_extensions-4.16.0.tar.gz"
    sha256 "dc98"
  end

  resource "linkify-it-py" do
    url "https://files.pythonhosted.org/packages/45/98/7a1a/linkify_it_py-2.2.0.zip"
    sha256 "907a"
  end
end
'''


def test_extracts_one_pin_per_resource():
    assert formula_pins.pins(FORMULA) == [
        "pyobjc-core==13.0",
        "typing-extensions==4.16.0",
        "linkify-it-py==2.2.0",
    ]


def test_ignores_the_main_url():
    assert not any("ssh-locker" in pin for pin in formula_pins.pins(FORMULA))
