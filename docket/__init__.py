#!/usr/bin/env python
import docker
import logging
import tarfile
import os
import json
import argparse
import sys
import tempfile
import shutil
import re
import hashlib

from subprocess import Popen
from os import walk
from fnmatch import fnmatch

logger = logging.getLogger('docket')
logging.basicConfig()

parser = argparse.ArgumentParser(description='')
parser.add_argument('-t', dest='tag', help='tag for final image')
parser.add_argument('--verbose', dest='verbose', action='store_true', help='verbose output', default=False)
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

c = docker.Client(base_url=base_url,
                  version='1.15',
                  timeout=10, tls=tls_config)

tag = args.tag or 'magic_beans'

logger.debug('building image with tag %s', tag)

buildpath = args.buildpath[0]

build_dockerfile = os.path.join(buildpath, 'Dockerfile')

def base_image_id(dockerfile):
    match = re.search('^FROM (?P<image>.*)', dockerfile)
    image_name = match.group('image')

    logger.info('pulling base image %s', image_name)
    res = c.pull(image_name, stream=True)
    for line in res:
        print json.loads(line).get('status', '')

    image, tag = image_name.split(':', 1)
    image_list = c.images(name=image)

    image_id = None
    for image in image_list:
        try:
            if image['RepoTags'].index(image_name) >= 0:
                image_id = image['Id']
        except ValueError:
            continue

    return image_id

## identify the ID of the FROM image we desired
parent_id = None
with open(build_dockerfile) as dockerfile:
    parent_id = base_image_id(dockerfile.read())

logger.info('base image id %s', parent_id)

private_home = os.path.join(os.path.expanduser('~'), '.docker', 'private')

private_layer = tempfile.NamedTemporaryFile()
private_layer_tar = tarfile.open(mode='w', fileobj=private_layer)
private_layer_tar.add(private_home, arcname='')
private_layer.seek(0)

# create a unique ID for the new private layer
private_layer_id = None
md = hashlib.md5()
md.update(parent_id)

with open(private_layer.name, 'rb') as tar:
    for chunk in iter(lambda: tar.read(128), ''):
        md.update(chunk)

private_layer_id = md.hexdigest()
private_layer_id += private_layer_id
private_layer.seek(0)

logger.info('private layer id %s', private_layer_id)

base_image_info = c.inspect_image(parent_id)
private_image_info = base_image_info;

private_image_info['Parent'] = parent_id
private_image_info['Id'] = private_layer_id
private_image_info['ContainerConfig']['Image'] = parent_id
private_image_info['Config']['Image'] = parent_id

private_image_info['parent'] = private_image_info['Parent']
private_image_info['id'] = private_image_info['Id']
private_image_info['container_config'] = private_image_info['ContainerConfig']
private_image_info['config'] = private_image_info['Config']
private_image_info['created'] = private_image_info['Created']

private_image = tempfile.NamedTemporaryFile()
private_image_tar = tarfile.open(mode='w', fileobj=private_image)
private_image_tar.add(private_layer.name, arcname=private_layer_id + '/layer.tar')

with tempfile.NamedTemporaryFile() as tmp:
    tmp.write('1.0')
    tmp.seek(0)
    tarinfo = private_image_tar.gettarinfo(name='VERSION', arcname=private_layer_id + '/VERSION', fileobj=tmp)
    private_image_tar.addfile(tarinfo, tmp)

with tempfile.NamedTemporaryFile() as tmp:
    json.dump(private_image_info, tmp)
    tmp.seek(0)
    tarinfo = private_image_tar.gettarinfo(name='json', arcname=private_layer_id + '/json', fileobj=tmp)
    private_image_tar.addfile(tarinfo, tmp)

private_image_tar.close()

need_load = True
try:
    inspect = c.inspect_image(private_layer_id)
    need_load = False
except:
    pass

if need_load:
    private_image.seek(0)

    logger.info('loading private image', private_layer_id)
    try:
        res = c.load_image(private_image)
    except Exception as err:
        print err
    finally:
        private_layer.close()

tmp_dockerfile = tempfile.NamedTemporaryFile()

with open(build_dockerfile) as dockerfile:
    content = dockerfile.read()
    content = re.sub(r'FROM (.*)\n', 'FROM ' + private_layer_id + '\n', content)
    tmp_dockerfile.write(content)

tmp_dockerfile.seek(0)

def no_dockerfile(tarinfo):
    if tarinfo.name == 'Dockerfile':
        return None
    return tarinfo

def fnmatch_any(relpath, patterns):
    return any([fnmatch(relpath, pattern) for pattern in patterns])

def tar(path, dockerfile, exclude=None):
    f = tempfile.NamedTemporaryFile()
    t = tarfile.open(mode='w', fileobj=f)
    for dirpath, dirnames, filenames in os.walk(path):
        relpath = os.path.relpath(dirpath, path)
        if relpath == '.':
            relpath = ''
        if exclude is None:
            fnames = filenames
        else:
            dirnames[:] = [d for d in dirnames
                           if not fnmatch_any(os.path.join(relpath, d),
                                              exclude)]
            fnames = [name for name in filenames
                      if not fnmatch_any(os.path.join(relpath, name),
                                         exclude)]
        for name in fnames:
            arcname = os.path.join(relpath, name)
            # ignore dockerfile because we will add our synthetic one
            t.add(os.path.join(path, arcname), arcname=arcname, filter=no_dockerfile)

    tarinfo = t.gettarinfo(name='Dockerfile', arcname='Dockerfile', fileobj=dockerfile)
    t.addfile(tarinfo, dockerfile)
    t.close()
    f.seek(0)
    return f

dockerignore = os.path.join(buildpath, '.dockerignore')
exclude = None
if os.path.exists(dockerignore):
    with open(dockerignore, 'r') as f:
        exclude = list(filter(bool, f.read().split('\n')))

logger.info('creating context tar from %s', buildpath)
context_tar = tar(buildpath, tmp_dockerfile, exclude=exclude)

logger.info('building')
res = c.build(fileobj=context_tar, tag=tag, stream=True, custom_context=True, rm=True)

for l in res:
    msg = json.loads(l)
    print msg['stream'],

context_tar.close()

build_tar = tempfile.NamedTemporaryFile()
logger.info('saving tar file from build %s', build_tar.name)

p_args = ['docker', 'save', '--output', build_tar.name, tag]
p = Popen(p_args)

res = p.wait()
if res != 0:
    sys.exit(res)

try:
    c.remove_image(tag)
except Exception:
    pass

extract_dir = tempfile.mkdtemp()
logger.info('extract the build tar %s', extract_dir)

try:
    with tarfile.open(mode='r', fileobj=build_tar) as tar:
        tar.extractall(path=extract_dir)

    # prune away image layers under private_id
    # we alreayd have them, don't need them again
    def prune(basepath, start_id):
        json_path = basepath + '/' + start_id + '/json'
        f = open(json_path, 'r+')
        content = json.load(f)
        f.close()
        if content.has_key('parent'):
            prune(basepath, content['parent'])
        elif content.has_key('Parent'):
            prune(basepath, content['Parent'])
        logger.debug('pruning %s', start_id)
        shutil.rmtree(basepath + '/' + start_id)

    logger.info('Splice out private layer id')
    prune(extract_dir, private_layer_id)

    for (dirpath, dirnames, filenames) in walk(extract_dir):
        for dir in dirnames:
            json_path = extract_dir + '/' + dir + '/json'

            f = open(json_path, 'r+')
            content = json.load(f)
            if content.has_key('parent') and content['parent'] == private_layer_id:
                content['parent'] = parent_id
                content['Parent'] = parent_id
                content['config']['Image'] = parent_id
                content['container_config']['Image'] = parent_id
                f.seek(0)
                json.dump(content, f)
                f.truncate()
            elif content.has_key('Parent') and content['Parent'] == private_layer_id:
                content['parent'] = parent_id
                content['Parent'] = parent_id
                content['config']['Image'] = parent_id
                content['container_config']['Image'] = parent_id
                f.seek(0)
                json.dump(content, f)
                f.truncate()
            f.close()

    logger.info('make final tarball')

    tmp_fpath = tempfile.mkstemp()
    try:
        tmp_file = tmp_fpath[0]
        tmp_path = tmp_fpath[1]

        with tarfile.open(name=tmp_path, mode='w') as tar:
            tar.add(extract_dir, arcname='')

        os.fsync(tmp_file)

        logger.info('loading final image %s', tmp_path)
        p_args = ['docker', 'load', '--input', tmp_path]
        p = Popen(p_args)

        res = p.wait()
        if res != 0:
            sys.exit(res)
    finally:
        os.remove(tmp_fpath[1])

finally:
    shutil.rmtree(extract_dir)
