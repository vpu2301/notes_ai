#!/usr/bin/env bash
# Create a self-signed code-signing identity for local builds, once.
#
# Why: macOS ties privacy permissions (microphone) to an app's code-signing
# "designated requirement". An ad-hoc signature (`codesign -s -`) has none
# beyond the binary's own hash, so every rebuild looks like a different app
# and the microphone grant you gave last time is silently dropped. Signing
# with one persistent certificate keeps the identity — and the permission —
# stable across builds.
#
#   scripts/make-signing-identity.sh              # creates "Notes AI Capture Dev"
#   NOTES_AI_SIGN_IDENTITY="My Cert" scripts/…    # a different common name
set -euo pipefail

NAME="${NOTES_AI_SIGN_IDENTITY:-Notes AI Capture Dev}"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

if security find-identity -v -p codesigning "$KEYCHAIN" 2>/dev/null | grep -q "\"$NAME\""; then
  echo "Signing identity \"$NAME\" already exists."
  exit 0
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/ext.cnf" <<CNF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $NAME
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
subjectKeyIdentifier = hash
CNF

openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -config "$WORK/ext.cnf" \
  -keyout "$WORK/key.pem" -out "$WORK/cert.pem" >/dev/null 2>&1
# Legacy PBE/MAC algorithms: OpenSSL 3's defaults (AES + SHA-256 MAC) are
# not readable by `security import`.
openssl pkcs12 -export -inkey "$WORK/key.pem" -in "$WORK/cert.pem" \
  -name "$NAME" -passout pass:notesai -out "$WORK/id.p12" \
  -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg sha1 >/dev/null 2>&1

# Import the identity and let codesign use the key without a prompt.
security import "$WORK/id.p12" -k "$KEYCHAIN" -P notesai \
  -T /usr/bin/codesign -T /usr/bin/security >/dev/null

# Trust it for code signing (user trust settings; may ask for your password).
security add-trusted-cert -r trustRoot -p codeSign -k "$KEYCHAIN" "$WORK/cert.pem"

if security find-identity -v -p codesigning "$KEYCHAIN" | grep -q "\"$NAME\""; then
  echo "Created signing identity \"$NAME\"."
else
  echo "Identity was imported but is not valid for code signing — open Keychain Access," >&2
  echo "find \"$NAME\", and set Trust → Code Signing to Always Trust." >&2
  exit 1
fi
