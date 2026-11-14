#pragma once
#include <stddef.h>
#include <stdint.h>

// ANCS lengths are bytes. The server accepts at most 4096 Unicode characters.
static constexpr size_t kMessageBytes = 4096;
static constexpr size_t kResponseBytes = 8192;

// Return only complete UTF-8 codepoints, including when ANCS itself truncates
// its attribute at the requested byte limit. Never emit invalid JSON UTF-8.
inline size_t utf8PrefixLength(const uint8_t* data, size_t length, size_t limit) {
  const size_t end = length < limit ? length : limit;
  size_t pos = 0;
  while (pos < end) {
    const uint8_t lead = data[pos];
    size_t width = lead < 0x80 ? 1 :
      (lead >= 0xc2 && lead <= 0xdf ? 2 :
       (lead >= 0xe0 && lead <= 0xef ? 3 :
        (lead >= 0xf0 && lead <= 0xf4 ? 4 : 0)));
    if (!width || pos + width > end) break;
    for (size_t i = 1; i < width; ++i) {
      if ((data[pos + i] & 0xc0) != 0x80) return pos;
    }
    if ((lead == 0xe0 && data[pos + 1] < 0xa0) ||
        (lead == 0xed && data[pos + 1] >= 0xa0) ||
        (lead == 0xf0 && data[pos + 1] < 0x90) ||
        (lead == 0xf4 && data[pos + 1] >= 0x90)) break;
    pos += width;
  }
  return pos;
}
