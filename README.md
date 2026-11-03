# actions
common Featuremine github actions

## macOS signing and notarization

See the [macOS actions guide](macos/README.md) for reusable Developer ID signing
setup, Apple notarization, organization configuration, and usage examples.

## building containers

Building container with inline cache

```bash
docker buildx build \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  --cache-from public.ecr.aws/p0w8t0l8/ci-hosted-gh-rocky8-cmake3.24-gcc13.2.0:latest \
  -f hosted-gh-rocky8-cmake3.24-gcc13.2.0.docker \
  -t public.ecr.aws/p0w8t0l8/ci-hosted-gh-rocky8-cmake3.24-gcc13.2.0:latest .
```

Push container

```bash
docker buildx build \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  --cache-from public.ecr.aws/p0w8t0l8/ci-hosted-gh-rocky8-cmake3.24-gcc13.2.0:latest \
  -f hosted-gh-rocky8-cmake3.24-gcc13.2.0.docker \
  -t public.ecr.aws/p0w8t0l8/ci-hosted-gh-rocky8-cmake3.24-gcc13.2.0:latest \
  --push .
```