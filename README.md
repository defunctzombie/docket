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
