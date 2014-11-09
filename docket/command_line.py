import argparse
import docker
import logging
import os
import docket

logger = logging.getLogger('docket')
logging.basicConfig()

parser = argparse.ArgumentParser(description='')
parser.add_argument('-t --tag', dest='tag', help='tag for final image')
parser.add_argument('--verbose', dest='verbose', action='store_true', help='verbose output', default=False)
parser.add_argument('--no-cache', dest='no_cache', action='store_true', help='Do not use cache when building the image', default=False)
parser.add_argument('buildpath', nargs='*')

args = parser.parse_args()

if args.verbose:
    logger.setLevel(logging.DEBUG)

cert_path = os.environ.get('DOCKER_CERT_PATH', '')
tls_verify = os.environ.get('DOCKER_TLS_VERIFY', '0')

base_url = os.environ.get('DOCKER_HOST', 'tcp://127.0.0.1:2375')
base_url = base_url.replace('tcp:', 'https:')
tls_config = None

if cert_path:
    tls_config = docker.tls.TLSConfig(verify=tls_verify,
        client_cert=(os.path.join(cert_path, 'cert.pem'), os.path.join(cert_path, 'key.pem')),
        ca_cert=os.path.join(cert_path, 'ca.pem')
    )

client = docker.Client(base_url=base_url, version='1.15', timeout=10, tls=tls_config)

tag = args.tag or None
buildpath = args.buildpath[0]

def main():
    docket.build(client=client, tag=tag, buildpath=buildpath, no_cache=args.no_cache)
    exit()

if __name__ == '__main__':
    main()
