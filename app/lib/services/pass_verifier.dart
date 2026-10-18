import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import '../models.dart';

enum VerifyError { malformed, badSignature }

class VerifyResult {
  const VerifyResult.ok(PassToken this.token) : error = null;
  const VerifyResult.fail(VerifyError this.error) : token = null;

  final PassToken? token;
  final VerifyError? error;
}

/// Checks a scanned pass entirely on the phone.
///
/// Token format (see the build spec, api/signing.py):
///   base64url(payload) + "." + base64url(Ed25519 signature over payload)
/// with the payload being compact JSON such as
///   {"v":1,"p":"<pass uuid>","e":"moksha26","d":[1,2,3],"iat":1761300000}
class PassVerifier {
  PassVerifier._(this._publicKey);

  final SimplePublicKey _publicKey;
  final _ed25519 = Ed25519();

  /// Throws [FormatException] if the key is not a 32-byte base64url string.
  factory PassVerifier.fromBase64Url(String key) {
    final bytes = decodeBase64Url(key.trim());
    if (bytes.length != 32) {
      throw FormatException(
          'Ed25519 public key must be 32 bytes, got ${bytes.length}');
    }
    return PassVerifier._(SimplePublicKey(bytes, type: KeyPairType.ed25519));
  }

  Future<VerifyResult> verify(String raw) async {
    final parts = raw.trim().split('.');
    if (parts.length != 2 || parts[0].isEmpty || parts[1].isEmpty) {
      return const VerifyResult.fail(VerifyError.malformed);
    }

    final Uint8List body;
    final Uint8List sig;
    try {
      body = decodeBase64Url(parts[0]);
      sig = decodeBase64Url(parts[1]);
    } on FormatException {
      return const VerifyResult.fail(VerifyError.malformed);
    }
    if (sig.length != 64) return const VerifyResult.fail(VerifyError.malformed);

    // Check the signature before trusting anything in the payload.
    final ok = await _ed25519.verify(
      body,
      signature: Signature(sig, publicKey: _publicKey),
    );
    if (!ok) return const VerifyResult.fail(VerifyError.badSignature);

    try {
      final json = jsonDecode(utf8.decode(body));
      if (json is! Map<String, dynamic>) throw const FormatException();
      final passId = json['p'];
      final event = json['e'];
      final days = json['d'];
      if (passId is! String || event is! String || days is! List) {
        throw const FormatException();
      }
      return VerifyResult.ok(PassToken(
        version: (json['v'] as num?)?.toInt() ?? 1,
        passId: passId,
        eventId: event,
        days: days.map((d) => (d as num).toInt()).toList(),
        issuedAt: (json['iat'] as num?)?.toInt() ?? 0,
      ));
    } catch (_) {
      // Signed by our key but not a payload we understand.
      return const VerifyResult.fail(VerifyError.malformed);
    }
  }
}

/// base64url without padding, as the server writes it.
Uint8List decodeBase64Url(String s) =>
    Uint8List.fromList(base64Url.decode(base64Url.normalize(s)));
