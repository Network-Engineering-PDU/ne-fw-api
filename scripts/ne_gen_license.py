# python3 ne_gen_license.py --sn aaaabbbbcccc --date 13/05/2030 --type "B1" -o ttfile.bin
# NOTA: libarchive instalado así: https://stackoverflow.com/questions/29225812/libarchive-public-error-even-after-installing-libarchive-in-python

import io
import tarfile
import argparse
from datetime import datetime
import gzip
import libarchive

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding

import pickle
import base64

PRIVATE_KEY="""
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCmVierPp1iVp5z
imxoLrr0grKN0lEoggh3ZmNERSYsCTmeWjUbtHQ4QJdWhY2dbNbUrem4BubGHOAv
i0sWs4cRmaxCZ3Lw9G9BM6QV/V2BbfEZCc+um4O83hia+B85NBVYcHAnndMplbzK
U0HHwplqX6bYBcrScSHXx4KMlTVnBFTalaJhHmru2PL/uKNpcqVA6hkdaXSxKk11
LS8rARkcAYqaskBfRjWYRd4LnRluC16uZWUNwclKJWSk3RN/+a8OOlbGEMNvpXTZ
7xaMoCNylJDOM72EXi1Nw9Zkyup7S3anIOslmOWkboDgkMGyaPGhMGFtvDe1d84U
xTsBVUHfAgMBAAECggEAArENNkeum0tEiCEazPrImrFMu1/GYW3tPiVhgNbPndHO
ZWIXTun2IXzmFgfWOVBsD4f66rft3xHTjOFnpyfjjSTb9T0gTobeEAOKabKuYyxI
xPt0KWKp2JINeuB9/Np7Z/F11yZGJvud0PZU76sV+XMvy3oYhJxBDHFVivnVIeQY
3hXS+bwGq+VzM3fOURegliynNGjA+bWzPRbWnCI0shFmsVMlT20RaFbF7s85MYPG
iMFvk2kZfS8D8f5isM/Orxo1tYpm74pQcy94FDbLssxGimoodHEqhv4jdqzTnYcL
M4rvw4XrDaKv31K5mwVHNuV8usI1LRPIAG9w3kksuQKBgQDXoQMQcGbZMzhtieZv
YoTriWI95k6LdT4lX/BwBCyu2cN9WFOWcHLowW1qh52i5PPlvR9x8ql0rJ+XbhV7
l/T3GAqDAGBodw4EPGzeq3x0VYL4DdCU90rnNsCSo6/TXMv4fi7ya1LwKD2C+EAe
Vdg9tWlUuOuCiho37rxIzQw3RwKBgQDFepUXDkmi5AgOeNY8+7ecErhn7w79Zj65
781qTtM/0+a5cMG5XWn4nVmIQXSo7gCmE3AdJU/gMb0M0cvk3Sf2oCeqT/tQe/ia
nkCdlV8Wpk7zOpsxlEm3RB0awxZvBbdw+6Z2JHGDK96Np/WmMvPcEjtATjy/ewlS
BdKPDn8cqQKBgA9ENxNS4fU+yx/2Q3pfX0nN0EbRp334Lw42XK+RnBhFErItLr3X
+ErCZxzDvUVrMFlzqmZG5/h6wFHYWW0GtTFJYnUj8a9zvmpOXObm/Ui/RSaK09m4
KHV2SuwW6rvsNgTB6lD/iD+4maJMMT30lfrIfUyiSwpS/Mg4/tuoqNTBAoGAFftK
IzHc8nvNhcbfmhQu4PmYe0E5+uzpqIrP47h4fU9aDGRHvBlw1VK2h5s5oCA2BEZ/
oU7o8Dy5HXcw6f3QF/zFzYhvograpmNdL+1Tk1LZ0OtCISeveO3lC3iRw7PwMmxg
oB/4XrCAamY6ytA7ItEItWTAEFRiujWZtYDYl1kCgYEAlXxl3TwRsLdNGEh34gvZ
dAw13uV90rE8QsAeKBDwtow+b0A8Xpkbyhc+TiDQqEqdwmKjSPNcrj94E+o3kkFP
OS7QUiPai5XzRg6SeWy+kwSdJM5/B5WRBA1e8xBwXId5Q6IrEfNoNqV98dW/JHva
1+CJB4T6zWmnUSIGLtSfN9g=
-----END PRIVATE KEY-----
"""

parser = argparse.ArgumentParser(description='Network Engineering licenses generator.')
parser.add_argument('--date', '-d', type=lambda d: datetime.strptime(d, '%d/%m/%Y'), default='01/01/2000',
                    help='License expiration date DD/MM/YYYY')
parser.add_argument('--type', '-t', default='A1', choices=['A1', 'A2', 'B1', 'B2'],
                    help='License type [A1, A2, B1, B2]')
parser.add_argument('--output', '-o', default='ttfile.bin',
                    help='Output path. Name must be ttfile.bin')
parser.add_argument('--sn', '-s', required=True,
                    help='Serial number of the target device')

args = parser.parse_args()

epoch_time = int((args.date - datetime(1970, 1, 1)).total_seconds())

#with open(args.output, 'w+') as f:
    #f.write(f"{epoch_time},{args.type}")

#tar --owner=0 --group=0 -C $TMP_FOLDER -czf $TMP_RESULTS/data.tar.gz .
#openssl dgst -sha256 -sign "$KEYFILE" -out $TMP_RESULTS/sign $TMP_RESULTS/data.tar.gz
#cpio --quiet -H crc -D $TMP_RESULTS -ov << EOF > ttfile.bin 2>/dev/null
#sign
#data.tar.gz
#EOF

license_text = f"{args.sn},{epoch_time},{args.type}"

key = serialization.load_pem_private_key(PRIVATE_KEY.encode(), password=None, backend=default_backend())

#public_key = key.public_key()

license_sign = key.sign(
        license_text.encode(),
        padding.PKCS1v15(),
        hashes.SHA256()
)

license_data = {
        "license": license_text,
        "signature": license_sign
}


license_file = base64.b64encode(pickle.dumps(license_data)).decode('utf-8')

if args.output != "ttfile.bin":
    with open(args.output, 'w') as f:
        f.write(license_file)

    print(f"License generated in {args.output}. Type: {args.type}. Date: {args.date}. SN: {args.sn}")
    exit(0)

script = "#!/bin/bash\n" \
        "cat << EOF > /home/root/.ne/license\n" \
        f"{license_file}\n" \
        "EOF\n" \
        "echo License installed successfully\n"

scriptFile = io.BytesIO(script.encode())

tar_stream = io.BytesIO()
with gzip.GzipFile(fileobj=tar_stream, mode='wb') as gz:
    with tarfile.open(fileobj=gz, mode='w') as tar:
        tarinfo = tarfile.TarInfo('script.sh')
        tarinfo.size = len(scriptFile.getvalue())
        tar.addfile(tarinfo, scriptFile)


sign = key.sign(
        tar_stream.getvalue(),
        padding.PKCS1v15(),
        hashes.SHA256()
)

signFile = io.BytesIO(sign)

with libarchive.Archive(args.output, 'w', "cpio") as a:
    #a.write(libarchive.Entry("data.tar.gz"), tar_stream.getvalue())
    a.write("data.tar.gz", tar_stream.getvalue())
    a.write("sign", signFile.getvalue())
    #a.write(libarchive.Entry("data.tar.gz"), open("ttfile.tar.gz",'rb').read())


print(f"License update file generated in {args.output}. Type: {args.type}. Date: {args.date}. SN: {args.sn}")
