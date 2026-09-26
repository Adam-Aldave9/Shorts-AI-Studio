// Providers limit prompts in UTF-8 bytes, not characters: an em dash is one character but
// three bytes.

const encoder = new TextEncoder();

export function utf8Bytes(text: string): number {
  return encoder.encode(text).length;
}
