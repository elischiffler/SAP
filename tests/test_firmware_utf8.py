"""Exercise the firmware's UTF-8 boundary helper with a native C++ compiler."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_firmware_preserves_complete_characters_at_every_capture_boundary(tmp_path):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("Native C++ compiler is unavailable")
    include = Path(__file__).resolve().parents[1] / "ESP32_BLE_NotificationForwarder/include"
    source = tmp_path / "utf8.cpp"
    source.write_text(
        r"""
#include "notification_limits.h"
#include <cassert>
#include <string>
int main() {
  const std::string text = "A\xc2\xa3\xe2\x82\xac\xf0\x9f\x99\x82Z";
  const size_t boundaries[] = {0, 1, 3, 6, 10, 11};
  for (size_t received = 0; received <= text.size(); ++received) {
    for (size_t cap = 0; cap <= text.size() + 1; ++cap) {
      size_t expected = 0;
      for (size_t boundary : boundaries)
        if (boundary <= received && boundary <= cap) expected = boundary;
      assert(utf8PrefixLength((const uint8_t*)text.data(), received, cap) == expected);
    }
  }
  for (const std::string invalid : {"\xc0\x80", "\xed\xa0\x80", "\xf4\x90\x80\x80", "\xe2!x"})
    assert(utf8PrefixLength((const uint8_t*)invalid.data(), invalid.size(), 4096) == 0);
  std::string longText(4095, 'a');
  longText += "\xf0\x9f\x99\x82";
  assert(utf8PrefixLength((const uint8_t*)longText.data(), longText.size(), kMessageBytes) == 4095);
}
"""
    )
    executable = tmp_path / "utf8"
    subprocess.run(
        [compiler, "-std=c++11", "-I", str(include), str(source), "-o", str(executable)],
        check=True,
        capture_output=True,
    )
    subprocess.run([str(executable)], check=True, capture_output=True)
