import hashlib
import hmac
import time
from datetime import datetime
from urllib import parse

import dateutil.parser
import requests

algorithm = "AWS4-HMAC-SHA256"
region = "eu-central-1"
service = "execute-api"

host = "api.energy.ch"

_credentials = None
_credentials_expire = 0


def get_signature_key(key, datestamp, region_name, service_name):
    """
    Does some hashing magic (Don't ask me, I just do what Amazon tells me so please don't hurt me)
    """

    def sign(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = sign(("AWS4" + key).encode("utf-8"), datestamp)
    k_region = sign(k_date, region_name)
    k_service = sign(k_region, service_name)
    k_signing = sign(k_service, "aws4_request")

    return k_signing


def get_credentials():
    """
    Returns a new set of valid credentials that can be used to sign the request
    """

    global _credentials
    global _credentials_expire

    if time.time() > _credentials_expire:
        resp = requests.get("https://api.energy.ch/sts/energych-player")
        data = resp.json()

        _credentials = (data["accessKeyId"], data["secretAccessKey"], data["sessionToken"])
        _credentials_expire = dateutil.parser.parse(data["expires"], tzinfos=0).timestamp()

    return _credentials


def get_playouts():
    """
    Return a list with the past 30 songs where the first element is the current song

    It looks complicated... And it is complicated... but it works?
    """

    access_key, secret_key, session_token = get_credentials()

    t = datetime.utcnow()
    amz_date = t.strftime("%Y%m%dT%H%M%SZ")
    datestamp = t.strftime("%Y%m%d")

    credential_scope = "{}/{}/{}/aws4_request".format(datestamp, region, service)

    params = [
        ("X-Amz-Algorithm", algorithm),
        ("X-Amz-Credential", "{}/{}".format(access_key, credential_scope)),
        ("X-Amz-Date", amz_date),
        ("X-Amz-Security-Token", session_token),
        ("X-Amz-SignedHeaders", "host")
    ]

    canonical_uri = "/broadcast/channels/bern/playouts"
    payload_hash = hashlib.sha256("".encode("utf-8")).hexdigest()
    canonical_headers = "host:" + host + "\n"
    canonical_querystring = "&".join(["{}={}".format(key, parse.quote_plus(value)) for key, value in params])

    canonical_request = "GET" + "\n" + canonical_uri + "\n" + canonical_querystring + "\n" + canonical_headers + "\n" + "host" + "\n" + payload_hash

    string_to_sign = "\n".join((
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    ))

    signing_key = get_signature_key(secret_key, datestamp, region, service)
    signature = hmac.new(signing_key, (string_to_sign).encode("utf-8"), hashlib.sha256).hexdigest()

    params.append(("X-Amz-Signature", signature))

    resp = requests.get("https://api.energy.ch/broadcast/channels/bern/playouts", params=params)

    return resp.json()


if __name__ == "__main__":
    print(get_playouts()[0])  # just a test
