# docket

Build docker images with secrets. Use it just like the `docker build` command.

## install

```
pip install git+git://github.com/defunctzombie/docket.git
```

## Use

Put some files into `$HOME/.docker/private`. They will be available during the build process.

Use docket like you would use `docker build`

```shell
docket -t foobar <path/to/build/root>
```

## Private Files

Any files in `$HOME/.docker/private` will be available during the build process. The folder structure under this directory will mirror the folder structure under `/` in the container.

These private files will not appear in any layer of the final image.

## How it works

*Note*: You need to understand docker layered file system internals for this to make sense.

Docket will examine your Dockerfile and locate the `FROM` image. It will create a new layer with the private files in `$HOME/.docker/private` and apply it to this base image.

It will then create a new temporary Dockerfile copy of your original Dockerfile and alter the `FROM` entry to point to this newly created image (which contains the private layer). Docket will package up your original build context and this new Dockerfile (replacing your original in the context) and send it over to the docker daemon to build.

After a successful build, docket will "download" (using the docker save feature) the image and unpackage it. This will result in a folder for every layer of the image. Docket will find the layer which references the "private" image it created and update the layer json to point to the original base image id you requested. It will then remove the private layer files and create a tarball to send back to docker (using the load feature).

This final image will contain no history of the private layer.
