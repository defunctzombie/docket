# docker-build

Build docker images with secrets. Use it just like the `docker build` command.

```shell
docker-build -t foobar <path/to/build/root>
```

Will source any files in `$HOME/.docker/private` into the image build context before building the Dockerfile and then remove the private files completely from the final image history. They will not appear in any previous layer of the image.
