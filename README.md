# actions
common Featuremine github actions

## building containers

Building container with inline cache

```bash
docker buildx build \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  -f hosted-gh-ubuntu20.04-gcc10.2.0.docker \
  -t public.ecr.aws/p0w8t0l8/ci-hosted-gh-ubuntu20.04-gcc10.2.0:latest .
```

Push container

```bash
docker buildx build \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  -f hosted-gh-ubuntu20.04-gcc10.2.0.docker \
  -t public.ecr.aws/p0w8t0l8/ci-hosted-gh-ubuntu20.04-gcc10.2.0:latest \
  --push .
```