import pyotp
import qrcode
import sys


def setup_user(username):
    secret = pyotp.random_base32()
    print(f"Setting up TOPT for {username}")
    print(f"Secret: {secret}")
    print("Add the following to your .env file:")
    print(f"TOTP_SECRET_{username.upper()}={secret}")

    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=f"{username}@zero-spice", issuer_name="Zero-Spice")
    img = qrcode.make(uri)
    img.save(f"totp_qr_{username}.png")
    print(f"QR Code generated: totp_qr_{username}.png")
    print(f"Or, use this URI: {uri}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 setup_totp.py <username>")
        sys.exit(1)
    setup_user(sys.argv[1])
