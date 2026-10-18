// Checks the app verifies passes exactly as the server signs them.
// Vectors come from tools/make_test_passes.py (test key, not the fest key).
//
//   flutter test

import 'package:flutter_test/flutter_test.dart';
import 'package:moksha_gate/services/pass_verifier.dart';

const _publicKey = 'wRc3Zk04CZpfOEOfnxr76l6PLU4hv8s4Rwpx7iKp8-o';

const _validAllDays =
    'eyJ2IjoxLCJwIjoiMTI4YjJmMzMtMGM1Yy03ZmQwLWE2YTMtYTQ1MDY1MTMyNzBlIiwiZSI6Im1va3NoYTI2IiwiZCI6WzEsMiwzXSwiaWF0IjoxNzkyMzI5MjU5fQ'
    '.ymfcuCVKXaOrMGM4lgCsIBlkSZT4pgd42ou48-cWOM2yiNKR6sXDOminy0DUbxlNXrC-I9iYEh-HObv6NSOFDg';

const _validDay2 =
    'eyJ2IjoxLCJwIjoiMThmMTM1ZDItNWY1NS03MjAzLTMwMTgtNTBjNWEzOGZkNTQ3IiwiZSI6Im1va3NoYTI2IiwiZCI6WzJdLCJpYXQiOjE3OTIzMjkyNTl9'
    '.dfUCgN8P0Eo8iAaf24qzj4VydeoppYTt4ommK3cWfHHUwpNeR1RfsNy_PhSDM5fFgRr7e6Jekg9kHlpJV7jQBg';

// Payload of another pass, glued to a real signature.
const _forged =
    'eyJ2IjoxLCJwIjoiM2U3ZDFiZmItYzdhMi1lYTIwLWIyZjEtNGM5NDJlMDUzMTlhIiwiZSI6Im1va3NoYTI2IiwiZCI6WzEsMiwzXSwiaWF0IjoxNzkyMzI5MjU5fQ'
    '.RRU9MBzukiPOtIhUhLyvEod47subHNgZwUtxGIw9Zlh7kpDTzv8GgyyByzfuXRY61RlCd9izMLHIb9KWtGI-Dg';

void main() {
  final verifier = PassVerifier.fromBase64Url(_publicKey);

  test('accepts a pass signed by the server key', () async {
    final r = await verifier.verify(_validAllDays);
    expect(r.error, isNull);
    expect(r.token!.passId, '128b2f33-0c5c-7fd0-a6a3-a4506513270e');
    expect(r.token!.eventId, 'moksha26');
    expect(r.token!.days, [1, 2, 3]);
  });

  test('reads the valid days', () async {
    final r = await verifier.verify(_validDay2);
    expect(r.token!.days, [2]);
  });

  test('rejects an edited pass', () async {
    final r = await verifier.verify(_forged);
    expect(r.error, VerifyError.badSignature);
  });

  test('rejects a changed signature', () async {
    // First signature character: 'y' -> 'z' changes real signature bits.
    final dot = _validAllDays.indexOf('.');
    final tampered = '${_validAllDays.substring(0, dot + 1)}z'
        '${_validAllDays.substring(dot + 2)}';
    final r = await verifier.verify(tampered);
    expect(r.error, VerifyError.badSignature);
  });

  test('treats other QR codes as not a pass', () async {
    for (final raw in ['https://example.com', '', 'a.b', 'abc', '...']) {
      final r = await verifier.verify(raw);
      expect(r.error, VerifyError.malformed, reason: raw);
    }
  });

  test('rejects a public key of the wrong length', () {
    expect(() => PassVerifier.fromBase64Url('AAAA'), throwsFormatException);
  });
}
